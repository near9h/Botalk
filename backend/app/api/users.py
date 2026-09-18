"""用户管理 API — admin-only。

提供 /api/users 列表/增/改/启停/重置密码/删除。
所有写操作均接入 audit log。
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, require_admin, require_user, verify_password
from app.db.models import User
from app.db.session import get_session
from app.schemas import (
    UserChangePassword,
    UserCreate,
    UserOut,
    UserResetPasswordOut,
    UserUpdate,
)
from app.services import audit as audit_service

router = APIRouter()


_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*"


def _random_password(length: int = 12) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


async def _count_admins(session: AsyncSession) -> int:
    result = await session.execute(
        select(sa_func.count(User.id)).where(User.role == "admin")
    )
    return int(result.scalar_one() or 0)


@router.get("", response_model=list[UserOut])
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[User]:
    """列出全部用户（含 disabled）。admin-only。"""
    result = await session.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
    admin: Annotated[User, Depends(require_admin)],
) -> User:
    existing = (
        await session.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在",
        )

    password = payload.password or _random_password()
    user = User(
        username=payload.username,
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(password),
        role=payload.role,
        status="active",
        created_by_id=admin.id,
    )
    session.add(user)
    await session.flush()  # to get id
    # 在 password 还在内存里时先把"初始密码"也带进 audit detail；
    # 仅这一次回写，随后就 commit。
    await audit_service.log(
        session,
        ctx,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
        detail={"role": user.role, "initial_password": password},
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
    admin: Annotated[User, Depends(require_admin)],
) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    data = payload.model_dump(exclude_none=True)
    if "status" in data and data["status"] == "disabled" and user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    if "role" in data and data["role"] == "user" and user.role == "admin":
        admins_before = await _count_admins(session)
        if admins_before <= 1:
            raise HTTPException(status_code=400, detail="至少保留一名管理员")

    for k, v in data.items():
        setattr(user, k, v)
    await audit_service.log(
        session,
        ctx,
        action="user.update",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
        detail={"changed": list(data.keys())},
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.post(
    "/{user_id}/reset-password",
    response_model=UserResetPasswordOut,
)
async def reset_password(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
    _admin: Annotated[User, Depends(require_admin)],
) -> UserResetPasswordOut:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    new_pw = _random_password()
    user.password_hash = hash_password(new_pw)
    await audit_service.log(
        session,
        ctx,
        action="user.reset_password",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
    )
    await session.commit()
    return UserResetPasswordOut(username=user.username, new_password=new_pw)


@router.post(
    "/{user_id}/change-password",
    response_model=UserResetPasswordOut,
)
async def change_password(
    user_id: int,
    payload: UserChangePassword,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
    actor: Annotated[User, Depends(require_user)],
) -> UserResetPasswordOut:
    """Self-service password change (also open to admins).

    Authorization:
      * The user themselves must supply the correct `old_password`.
      * An admin can rotate any user's password without knowing the old
        one (they typically use `reset-password` instead, but this is a
        generic primitive so admin tooling can call it too).

    The endpoint always returns the new password once so the UI can
    confirm. (For self-service the user just typed it themselves so this
    is mostly a no-op echo; we keep the response shape symmetric with
    `reset-password`.)
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    is_self = user.id == actor.id
    if not is_self and actor.role != "admin":
        raise HTTPException(status_code=403, detail="只能修改自己的密码")
    if is_self:
        if not payload.old_password or not verify_password(
            payload.old_password, user.password_hash
        ):
            raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    await audit_service.log(
        session,
        ctx,
        action="user.change_password",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
        detail={"self_service": is_self},
    )
    await session.commit()
    return UserResetPasswordOut(username=user.username, new_password=payload.new_password)


@router.post("/{user_id}/enable", response_model=UserOut)
async def enable_user(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
    _admin: Annotated[User, Depends(require_admin)],
) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.status = "active"
    await audit_service.log(
        session,
        ctx,
        action="user.enable",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
    admin: Annotated[User, Depends(require_admin)],
) -> None:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    if user.role == "admin":
        admins_before = await _count_admins(session)
        if admins_before <= 1:
            raise HTTPException(status_code=400, detail="至少保留一名管理员")
    # 软删除：禁用账号但保留数据（消息、bot 归属等仍可追溯）
    user.status = "disabled"
    await audit_service.log(
        session,
        ctx,
        action="user.delete",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
        detail={"soft": True},
    )
    await session.commit()