"""Group + membership CRUD endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Bot, Group, GroupMember
from app.db.session import get_session
from app.schemas import GroupCreate, GroupOut

router = APIRouter()


def _to_out(group: Group) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        mode=group.mode,
        max_rounds=group.max_rounds,
        created_at=group.created_at,
        bot_ids=[m.bot_id for m in group.members],
    )


@router.get("", response_model=list[GroupOut])
async def list_groups(session: AsyncSession = Depends(get_session)) -> list[GroupOut]:
    result = await session.execute(
        select(Group).options(selectinload(Group.members)).order_by(Group.id)
    )
    return [_to_out(g) for g in result.scalars().all()]


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate, session: AsyncSession = Depends(get_session)
) -> GroupOut:
    group = Group(
        name=payload.name,
        description=payload.description,
        mode=payload.mode,
        max_rounds=payload.max_rounds,
    )
    # Verify bots exist before associating.
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
    await session.commit()
    await session.refresh(group, attribute_names=["members"])
    return _to_out(group)


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: int, session: AsyncSession = Depends(get_session)) -> GroupOut:
    result = await session.execute(
        select(Group).options(selectinload(Group.members)).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    return _to_out(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, session: AsyncSession = Depends(get_session)) -> None:
    group = await session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    await session.delete(group)
    await session.commit()


@router.post("/{group_id}/members/{bot_id}", response_model=GroupOut)
async def add_member(
    group_id: int, bot_id: int, session: AsyncSession = Depends(get_session)
) -> GroupOut:
    result = await session.execute(
        select(Group).options(selectinload(Group.members)).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if not await session.get(Bot, bot_id):
        raise HTTPException(status_code=404, detail="bot not found")
    if any(m.bot_id == bot_id for m in group.members):
        return _to_out(group)
    next_order = max((m.join_order for m in group.members), default=-1) + 1
    group.members.append(GroupMember(bot_id=bot_id, join_order=next_order))
    await session.commit()
    await session.refresh(group, attribute_names=["members"])
    return _to_out(group)


@router.delete(
    "/{group_id}/members/{bot_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    group_id: int, bot_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    result = await session.execute(
        select(Group).options(selectinload(Group.members)).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    group.members = [m for m in group.members if m.bot_id != bot_id]
    await session.commit()