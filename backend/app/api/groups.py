"""Group + membership CRUD endpoints.

RBAC:
- GET /api/groups: admin 全集; user 仅看 scope='system' OR owner_id=self
- POST /api/groups: 普通用户自动 owner=self scope='user'; admin 可显式 system
- GET/PATCH/DELETE /api/groups/{public_id}: 不可见 → 404; 非 owner/admin → 403

Wire-facing 用 `public_id`（12 字符 base62），整数 id 仅作内部主键。
全部写操作接入 audit log。
"""
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_user
from app.db.models import Bot, Group, GroupMember, User
from app.db.session import get_session
from app.schemas import GroupCreate, GroupOut, GroupUpdate
from app.services import audit as audit_service

router = APIRouter()


_TOKEN_ALPHABET = string.ascii_letters + string.digits
_TOKEN_LENGTH = 12


def _gen_public_id() -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))


def _to_out(group: Group) -> GroupOut:
    return GroupOut(
        public_id=group.public_id,
        name=group.name,
        description=group.description,
        mode=group.mode,
        max_rounds=group.max_rounds,
        owner_id=group.owner_id,
        scope=group.scope,
        created_at=group.created_at,
        bot_ids=[m.bot_id for m in group.members],
    )


async def resolve_group(session: AsyncSession, public_id: str) -> Group | None:
    """wire-facing public_id (12 char base62) → Group or None."""
    return (
        await session.execute(
            select(Group)
            .options(selectinload(Group.members))
            .where(Group.public_id == public_id)
        )
    ).scalar_one_or_none()


@router.get("", response_model=list[GroupOut])
async def list_groups(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[GroupOut]:
    """admin 全集; user 仅看 system + 自己 owner 的群组。"""
    if user.role == "admin":
        result = await session.execute(
            select(Group).options(selectinload(Group.members)).order_by(Group.id)
        )
    else:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.members))
            .where(or_(Group.scope == "system", Group.owner_id == user.id))
            .order_by(Group.id)
        )
    return [_to_out(g) for g in result.scalars().all()]


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> GroupOut:
    # 普通用户：忽略 client 传的 scope，强制 'user' 且 owner=self
    scope = payload.scope if user.role == "admin" else "user"
    if scope != "system":
        scope = "user"

    # 生成唯一 public_id
    for _ in range(8):
        candidate = _gen_public_id()
        exists = (
            await session.execute(
                select(Group.id).where(Group.public_id == candidate)
            )
        ).scalar_one_or_none()
        if not exists:
            break
    else:
        raise HTTPException(status_code=500, detail="无法生成唯一 public_id")

    group = Group(
        public_id=candidate,
        name=payload.name,
        description=payload.description,
        mode=payload.mode,
        max_rounds=payload.max_rounds,
        scope=scope,
        owner_id=user.id if scope == "user" else None,
    )
    if payload.bot_ids:
        existing = await session.execute(
            select(Bot.id).where(Bot.id.in_(payload.bot_ids))
        )
        existing_ids = {row[0] for row in existing.all()}
        missing = set(payload.bot_ids) - existing_ids
        if missing:
            raise HTTPException(
                status_code=400, detail=f"bot ids not found: {sorted(missing)}"
            )
        for order, bid in enumerate(payload.bot_ids):
            group.members.append(GroupMember(bot_id=bid, join_order=order))
    session.add(group)
    await session.flush()
    await audit_service.log(
        session,
        ctx,
        action="group.create",
        target_type="group",
        target_id=group.public_id,
        target_name=group.name,
        detail={"scope": group.scope, "bot_ids": payload.bot_ids},
    )
    await session.commit()
    await session.refresh(group, attribute_names=["members"])
    return _to_out(group)


@router.get("/{public_id}", response_model=GroupOut)
async def get_group(
    public_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> GroupOut:
    group = await resolve_group(session, public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if (
        user.role != "admin"
        and group.scope != "system"
        and group.owner_id != user.id
    ):
        # 不可见 → 404（不暴露存在性）
        raise HTTPException(status_code=404, detail="group not found")
    return _to_out(group)


@router.patch("/{public_id}", response_model=GroupOut)
async def update_group(
    public_id: str,
    payload: GroupUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> GroupOut:
    group = await resolve_group(session, public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if user.role != "admin" and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只能修改自己创建的群组")
    data = payload.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(group, k, v)
    await audit_service.log(
        session,
        ctx,
        action="group.update",
        target_type="group",
        target_id=group.public_id,
        target_name=group.name,
        detail={"changed": list(data.keys())},
    )
    await session.commit()
    await session.refresh(group, attribute_names=["members"])
    return _to_out(group)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    public_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    group = await resolve_group(session, public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if group.scope == "system":
        raise HTTPException(status_code=403, detail="系统共享群组不可删除")
    if user.role != "admin" and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只能删除自己创建的群组")
    group_name = group.name
    await audit_service.log(
        session,
        ctx,
        action="group.delete",
        target_type="group",
        target_id=group.public_id,
        target_name=group_name,
    )
    await session.delete(group)
    await session.commit()


@router.post("/{public_id}/members/{bot_id}", response_model=GroupOut)
async def add_member(
    public_id: str,
    bot_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> GroupOut:
    group = await resolve_group(session, public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if user.role != "admin" and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只能修改自己创建的群组")
    if not await session.get(Bot, bot_id):
        raise HTTPException(status_code=404, detail="bot not found")
    if any(m.bot_id == bot_id for m in group.members):
        return _to_out(group)
    next_order = max((m.join_order for m in group.members), default=-1) + 1
    group.members.append(GroupMember(bot_id=bot_id, join_order=next_order))
    await audit_service.log(
        session,
        ctx,
        action="group.add_member",
        target_type="group",
        target_id=group.public_id,
        target_name=group.name,
        detail={"bot_id": bot_id},
    )
    await session.commit()
    await session.refresh(group, attribute_names=["members"])
    return _to_out(group)


@router.delete(
    "/{public_id}/members/{bot_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    public_id: str,
    bot_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    group = await resolve_group(session, public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if user.role != "admin" and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只能修改自己创建的群组")
    group.members = [m for m in group.members if m.bot_id != bot_id]
    await audit_service.log(
        session,
        ctx,
        action="group.remove_member",
        target_type="group",
        target_id=group.public_id,
        target_name=group.name,
        detail={"bot_id": bot_id},
    )
    await session.commit()