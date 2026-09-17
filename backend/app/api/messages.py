"""Message history endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message
from app.db.session import get_session
from app.schemas import MessageOut

router = APIRouter()


@router.get("", response_model=list[MessageOut])
async def list_messages(
    group_id: int = Query(..., description="Group ID to fetch history for"),
    run_id: int | None = Query(default=None, description="Optional session filter"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[Message]:
    stmt = select(Message).where(Message.group_id == group_id)
    if run_id is not None:
        stmt = stmt.where(Message.run_id == run_id)
    result = await session.execute(stmt.order_by(Message.id.asc()).limit(limit))
    return list(result.scalars().all())


@router.delete("", status_code=204)
async def clear_messages(
    group_id: int = Query(..., description="Group ID to wipe history for"),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete every message in the given group — used by the chat UI's
    "↻ 清空对话" button to start a fresh thread within the same group."""
    await session.execute(
        delete(Message).where(Message.group_id == group_id)
    )
    await session.commit()