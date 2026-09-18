"""Conversation session (run/task) listing endpoints.

Wire-facing 改用 `group_public_id`；普通用户不能查看不可见 group 的任务。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_user
from app.db.models import Group, Run, User
from app.db.session import get_session
from app.schemas import RunOut
from app.services import audit as audit_service

router = APIRouter()


async def _resolve_visible_group(
    session: AsyncSession, user: User, public_id: str
) -> Group | None:
    group = (
        await session.execute(select(Group).where(Group.public_id == public_id))
    ).scalar_one_or_none()
    if not group:
        return None
    if user.role != "admin" and group.scope != "system" and group.owner_id != user.id:
        return None
    return group


@router.get("", response_model=list[RunOut])
async def list_runs(
    group_public_id: str = Query(..., description="Group public id"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[RunOut]:
    group = await _resolve_visible_group(session, user, group_public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    result = await session.execute(
        select(Run)
        .where(Run.group_id == group.id)
        .order_by(Run.id.desc())
        .limit(limit)
    )
    runs = list(result.scalars().all())
    return [_to_out(r) for r in runs]


def _to_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,
        group_id=r.group_id,
        status=r.status,
        title=r.title or "",
        share_token=r.share_token or "",
        started_at=r.started_at,
        finished_at=r.finished_at,
        total_tokens=r.total_tokens,
        user_prompt=r.user_prompt,
        message_count=r.message_count or 0,
    )