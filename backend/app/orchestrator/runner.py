"""Persist group chat runs and messages."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Bot, Group, Message, Run


def _derive_title(prompt: str) -> str:
    """Make a short, user-facing title out of the task's first prompt.

    Empty prompts (a fresh "new task" with no user message yet) yield
    an empty string so the UI can show "新对话" / "未命名任务" instead.
    """
    p = (prompt or "").strip()
    if not p:
        return ""
    return p[:30]


async def get_group_with_members(
    session: AsyncSession, group_id: int
) -> Group | None:
    result = await session.execute(
        select(Group).options(selectinload(Group.members)).where(Group.id == group_id)
    )
    return result.scalar_one_or_none()


async def get_bots_in_order(
    session: AsyncSession, group: Group
) -> list[Bot]:
    if not group.members:
        return []
    bot_ids = [m.bot_id for m in sorted(group.members, key=lambda m: m.join_order)]
    result = await session.execute(
        select(Bot).where(Bot.id.in_(bot_ids))
    )
    bots_by_id = {b.id: b for b in result.scalars().all()}
    return [bots_by_id[bid] for bid in bot_ids if bid in bots_by_id]


async def start_run(session: AsyncSession, group_id: int, prompt: str) -> Run:
    """Create a new task (= run) for this user turn.

    `prompt` may be empty when the caller is opening a fresh empty task
    (the user clicked "新对话"). The row's title stays empty in that
    case and will be backfilled when the user actually sends a message.
    """
    run = Run(
        group_id=group_id,
        status="running",
        user_prompt=prompt,
        title=_derive_title(prompt),
        message_count=0,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def create_empty_task(session: AsyncSession, group_id: int) -> Run:
    """Create a pending task without any user message yet.

    Used by the UI's "新对话" button so the user can compose the first
    message into a fresh task instead of being dropped into whichever
    task they last left open. The title stays empty until the first
    message lands.
    """
    run = Run(
        group_id=group_id,
        status="pending",
        user_prompt="",
        title="",
        message_count=0,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def finish_run(session: AsyncSession, run_id: int, status: str, total_tokens: int) -> None:
    run = await session.get(Run, run_id)
    if not run:
        return
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.total_tokens = total_tokens
    await session.commit()


async def save_message(
    session: AsyncSession,
    run_id: int,
    group_id: int,
    role: str,
    content: str,
    bot_id: int | None = None,
    token_usage: int = 0,
) -> Message:
    msg = Message(
        run_id=run_id,
        group_id=group_id,
        role=role,
        bot_id=bot_id,
        content=content,
        token_usage=token_usage,
    )
    session.add(msg)
    # If this is the first user message of a still-untitled task,
    # backfill the title from the prompt now (so the history drawer
    # doesn't show a bunch of "未命名任务" entries).
    run = await session.get(Run, run_id)
    if run is not None:
        run.message_count = (run.message_count or 0) + 1
        if role == "user" and not run.title:
            run.title = _derive_title(content)
            # A pending task transitions to running the moment the
            # first message is sent.
            if run.status == "pending":
                run.status = "running"
    await session.commit()
    await session.refresh(msg)
    return msg