"""Task (a.k.a. Run) CRUD endpoints — the user-facing unit of navigation.

A task is one user turn + the multi-bot discussion it triggers. Every
chat conversation is bound to exactly one task: when the user clicks
「新会话」 they create a brand-new pending task; when they pick an old
thread from the history drawer they reopen an existing one.

This router is the canonical frontend-facing API. The older /api/runs
endpoints remain as a thin compatibility layer (same row format).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Run
from app.db.session import get_session
from app.orchestrator.runner import create_empty_task
from app.schemas import RunCreate, RunOut, RunUpdate

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
    """Look up a task by either its integer id or its share_token.

    The URL parameter on /api/tasks/{task_id} accepts both forms so the
    UI can pin to a shared link (`?task=<token>`) or call the legacy
    integer-id endpoint. Identifies a numeric string and dispatches.
    """
    if key.isdigit():
        return await session.get(Run, int(key))
    result = await session.execute(select(Run).where(Run.share_token == key))
    return result.scalar_one_or_none()


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def open_task(
    payload: RunCreate, session: AsyncSession = Depends(get_session)
) -> RunOut:
    """Open a fresh empty task in a group.

    The task is `pending` until the user actually sends the first
    message; at that point the orchestrator flips it to `running` and
    backfills the title from the prompt.
    """
    if not await session.get(Group, payload.group_id):
        raise HTTPException(status_code=404, detail="group not found")
    run = await create_empty_task(session, payload.group_id)
    if payload.title:
        # Optional: caller can pre-name the task. Useful if the UI
        # wants to surface "新对话" / "未命名任务" with a custom name.
        run.title = payload.title[:128]
        await session.commit()
        await session.refresh(run)
    return _to_out(run)


@router.get("", response_model=list[RunOut])
async def list_tasks(
    group_id: int,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[RunOut]:
    """List tasks for a group, newest first. Powers the history drawer."""
    if not await session.get(Group, group_id):
        raise HTTPException(status_code=404, detail="group not found")
    result = await session.execute(
        select(Run)
        .where(Run.group_id == group_id)
        .order_by(Run.id.desc())
        .limit(limit)
    )
    return [_to_out(r) for r in result.scalars().all()]


@router.get("/{task_id}", response_model=RunOut)
async def get_task(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> RunOut:
    run = await _resolve_task(session, task_id)
    if not run:
        raise HTTPException(status_code=404, detail="task not found")
    return _to_out(run)


@router.patch("/{task_id}", response_model=RunOut)
async def rename_task(
    task_id: str,
    payload: RunUpdate,
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    """Rename a task. Only the user-facing title is editable."""
    run = await _resolve_task(session, task_id)
    if not run:
        raise HTTPException(status_code=404, detail="task not found")
    if payload.title is not None:
        run.title = payload.title[:128]
    await session.commit()
    await session.refresh(run)
    return _to_out(run)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    """Delete a task and all its messages.

    Unlike group deletion this is cheap and reversible-by-recording:
    the user might want to wipe a single chat thread they regret.
    """
    run = await _resolve_task(session, task_id)
    if not run:
        raise HTTPException(status_code=404, detail="task not found")
    await session.delete(run)
    await session.commit()
