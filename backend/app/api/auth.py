"""Auth API: login, logout, register (only when user table empty), me.

接入审计：login 成功/失败、logout、register。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    clear_session_cookie,
    get_current_user,
    hash_password,
    make_token,
    set_session_cookie,
    verify_password,
)
from app.config import get_settings
from app.db.models import User
from app.db.session import get_session
from app.services import audit as audit_service

router = APIRouter()
settings = get_settings()


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=256)
    password: str = Field(min_length=8, max_length=256)


class MeOut(BaseModel):
    """Return current user detail (post RBAC)."""

    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    role: str
    status: str


@router.post("/login")
async def login(
    body: LoginBody,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
) -> MeOut:
    result = await session.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()
    # 同一错误信息：避免用户名枚举攻击
    bad = (
        not user
            or not verify_password(body.password, user.password_hash)
            or user.status == "disabled"
        )
    if bad:
        await audit_service.log(
            session,
            ctx,
            action="auth.login.fail",
            target_type="auth",
            target_id=body.username,
            target_name=body.username,
            status="failure",
            detail={"reason": "bad_credentials_or_disabled"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    user.last_login_at = datetime.now(tz=timezone.utc)
    token = make_token(user.id)
    set_session_cookie(response, token)
    await audit_service.log(
        session,
        ctx,
        action="auth.login",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
    )
    await session.commit()
    return MeOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
    )


@router.post("/logout")
async def logout(
    response: Response,
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    clear_session_cookie(response)
    await audit_service.log(
        session,
        ctx,
        action="auth.logout",
        target_type="auth",
        target_id=str(ctx.safe_actor()[0]) if ctx.actor else None,
        target_name=ctx.safe_actor()[1],
    )
    await session.commit()
    return {"ok": True}


@router.post("/register")
async def register(
    body: RegisterBody,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    ctx: Annotated[audit_service.AuditContext, Depends(audit_service.audit_ctx)],
) -> MeOut:
    """Only allowed when the users table is empty (i.e. first-run bootstrap)."""
    result = await session.execute(select(sa_func.count(User.id)))
    count = result.scalar_one() or 0
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="已有用户存在,请直接登录或联系管理员",
        )
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role="admin",  # 第一个用户默认是管理员
    )
    session.add(user)
    await session.flush()
    await audit_service.log(
        session,
        ctx,
        action="auth.register",
        target_type="user",
        target_id=str(user.id),
        target_name=user.username,
    )
    await session.commit()
    await session.refresh(user)
    set_session_cookie(response, make_token(user.id))
    return MeOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
    )


@router.get("/me")
async def me(
    user: Annotated[User | None, Depends(get_current_user)],
) -> MeOut | None:
    if user is None:
        return None
    return MeOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
    )