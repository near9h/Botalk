"""Conversation session (run/task) listing endpoints.

A "task" is one user prompt plus the full multi-bot discussion it produced —
the natural unit of "a session" in the chat history. The DB still calls this
row a Run (see app.db.models.Run), but the user-facing concept is a task;
the frontend talks to /api/tasks primarily and falls back to /api/runs for
backwards compatibility.

The `message_count` column is materialized on the runs table now, so we
no longer need a per-row COUNT(*) — that used to dominate the query as
history grew.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run
from app.db.session import get_session
from app.schemas import RunOut

router = APIRouter()


@router.get("", response_model=list[RunOut])
async def list_runs(
    group_id: int = Query(..., description="Group ID to list sessions for"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[RunOut]:
    result = await session.execute(
        select(Run)
        .where(Run.group_id == group_id)
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
