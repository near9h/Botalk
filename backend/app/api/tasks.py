"""Task (a.k.a. Run) CRUD — user-facing navigation unit.

Wire-facing 改用 group_public_id；run 行内部 group_id 仍是整数。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runs import _resolve_visible_group
from app.auth import require_user
from app.db.models import Group, Run, User
from app.db.session import get_session
from app.orchestrator.runner import create_empty_task
from app.schemas import RunCreate, RunOut, RunUpdate
from app.services import audit as audit_service

router = APIRouter()


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


async def _resolve_task(session: AsyncSession, key: str) -> Run | None:
    """Look up a task by either its integer id or its share_token."""
    if key.isdigit():
        return await session.get(Run, int(key))
    result = await session.execute(select(Run).where(Run.share_token == key))
    return result.scalar_one_or_none()


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def open_task(
    payload: RunCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> RunOut:
    """Open a fresh empty task in a group."""
    group = await _resolve_visible_group(session, user, payload.group_public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    run = await create_empty_task(session, group.id)
    if payload.title:
        run.title = payload.title[:128]
    await audit_service.log(
        session,
        ctx,
        action="task.create",
        target_type="task",
        target_id=run.share_token,
        target_name=run.title or "(空任务)",
        detail={"group_public_id": group.public_id},
    )
    await session.commit()
    await session.refresh(run)
    return _to_out(run)


@router.get("", response_model=list[RunOut])
async def list_tasks(
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
        .where(
            Run.group_id == group.id,
            # Hide empty drafts that were never sent — they pile up when the
            # user opens the group page but never actually types a message.
            ~and_(Run.status == "pending", Run.message_count == 0),
        )
        .order_by(Run.id.desc())
        .limit(limit)
    )
    return [_to_out(r) for r in result.scalars().all()]


@router.get("/{task_id}", response_model=RunOut)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> RunOut:
    run = await _resolve_task(session, task_id)
    if not run:
        raise HTTPException(status_code=404, detail="task not found")
    # 校验所属 group 对当前 user 可见
    grp = (
        await session.execute(select(Group).where(Group.id == run.group_id))
    ).scalar_one_or_none()
    if grp and (
        user.role == "admin"
        or grp.scope == "system"
        or grp.owner_id == user.id
    ):
        return _to_out(run)
    raise HTTPException(status_code=404, detail="task not found")


@router.patch("/{task_id}", response_model=RunOut)
async def rename_task(
    task_id: str,
    payload: RunUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> RunOut:
    run = await _resolve_task(session, task_id)
    if not run:
        raise HTTPException(status_code=404, detail="task not found")
    grp = (
        await session.execute(select(Group).where(Group.id == run.group_id))
    ).scalar_one_or_none()
    if grp and not (
        user.role == "admin"
        or grp.scope == "system"
        or grp.owner_id == user.id
    ):
        raise HTTPException(status_code=404, detail="task not found")
    if payload.title is not None:
        run.title = payload.title[:128]
    await audit_service.log(
        session,
        ctx,
        action="task.update",
        target_type="task",
        target_id=run.share_token,
        target_name=run.title,
        detail={"changed": ["title"]},
    )
    await session.commit()
    await session.refresh(run)
    return _to_out(run)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    run = await _resolve_task(session, task_id)
    if not run:
        raise HTTPException(status_code=404, detail="task not found")
    grp = (
        await session.execute(select(Group).where(Group.id == run.group_id))
    ).scalar_one_or_none()
    if grp and not (
        user.role == "admin"
        or grp.scope == "system"
        or grp.owner_id == user.id
    ):
        raise HTTPException(status_code=404, detail="task not found")
    share_token = run.share_token
    await audit_service.log(
        session,
        ctx,
        action="task.delete",
        target_type="task",
        target_id=share_token,
        target_name=run.title,
    )
    await session.delete(run)
    await session.commit()