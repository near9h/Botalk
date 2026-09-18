"""Streaming chat (SSE) endpoint. Wire-facing group_public_id."""
import asyncio
from dataclasses import asdict
from typing import Any
import json as jsonlib
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.auth import require_user
from app.config import get_settings
from app.db.models import Attachment, BotSkill, Group, Run, User  # noqa: F811
from app.db.session import get_session
from app.orchestrator.msghub import run_group_discussion
from app.orchestrator.runner import (
    finish_run,
    get_bots_in_order,
    get_group_by_public_id,
    save_message,
    start_run,
)
from app.schemas import ChatRequest
from app.services import audit as audit_service

router = APIRouter()
settings = get_settings()

_MENTION_RE = re.compile(r"@([\w一-鿿]+)")


def _extract_mentions(prompt: str) -> list[str]:
    return _MENTION_RE.findall(prompt)


async def _visible_group_check(session: AsyncSession, user: User, group: Group) -> bool:
    """普通用户不能对不可见群组发起对话；admin 全通。"""
    if user.role == "admin":
        return True
    return group.scope == "system" or group.owner_id == user.id


@router.post("/stream")
async def stream_chat(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> EventSourceResponse:
    group = await get_group_by_public_id(session, payload.group_public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if not await _visible_group_check(session, user, group):
        raise HTTPException(status_code=404, detail="group not found")
    bots = await get_bots_in_order(session, group)
    if not bots:
        raise HTTPException(status_code=400, detail="group has no bots")

    mode = payload.mode or group.mode
    max_rounds = payload.max_rounds or group.max_rounds or settings.default_max_rounds
    mentioned = _extract_mentions(payload.prompt)
    group_id_int = group.id  # 内部整数主键，后续 SQL 用

    # Resolve attachments → concatenated Markdown context (if any).
    extra_ctx_parts: list[str] = []
    if payload.attachment_ids:
        # Don't trust client-supplied attachment ids blindly — only inject
        # Markdown from attachments whose parent group the caller can see.
        atts = (
            await session.execute(
                select(Attachment).where(Attachment.id.in_(payload.attachment_ids))
            )
        ).scalars().all()
        visible_group_ids: set[int] = set()
        if atts:
            grp_rows = await session.execute(
                select(Group.id, Group.scope, Group.owner_id).where(
                    Group.id.in_({a.group_id for a in atts if a.group_id is not None})
                )
            )
            for gid, scope, owner_id in grp_rows.all():
                if (
                    user.role == "admin"
                    or scope == "system"
                    or owner_id == user.id
                ):
                    visible_group_ids.add(gid)
        for a in atts:
            # Unattached (ad-hoc) uploads are admin-only.
            if a.group_id is None:
                if user.role != "admin":
                    continue
            elif a.group_id not in visible_group_ids:
                continue
            extra_ctx_parts.append(f"### {a.filename}\n\n{a.content_md}\n")
    extra_context = "\n\n".join(extra_ctx_parts) if extra_ctx_parts else None

    # Resolve task by id or share_token (both still integer and opaque token).
    existing_run: Run | None = None
    if payload.task_token:
        existing_run = (
            await session.execute(
                select(Run).where(Run.share_token == payload.task_token)
            )
        ).scalar_one_or_none()
        if existing_run and existing_run.group_id != group_id_int:
            raise HTTPException(
                status_code=404, detail="task not found in this group"
            )
    elif payload.task_id is not None:
        existing_run = (
            await session.execute(
                select(Run).where(Run.id == payload.task_id)
            )
        ).scalar_one_or_none()
        if existing_run and existing_run.group_id != group_id_int:
            raise HTTPException(
                status_code=404, detail="task not found in this group"
            )

    run = existing_run or await start_run(session, group_id_int, payload.prompt)
    await audit_service.log(
        session,
        ctx,
        action="chat.run",
        target_type="task",
        target_id=run.share_token,
        target_name=run.title or "(无标题)",
        detail={
            "group_public_id": group.public_id,
            "mention_count": len(mentioned),
            "attachment_count": len(payload.attachment_ids or []),
        },
    )
    await session.commit()

    async def event_gen():
        # 重新拿一个干净的 session 用于 streaming，避免与请求 session 抢资源
        from app.db.session import SessionLocal
        from app.db.models import BotSkill, Skill

        async with SessionLocal() as ss:
            # Load each bot's enabled skills as plain dicts so the
            # orchestrator can inject tool/knowledge context per bot.
            bot_ids = [b.id for b in bots]
            skill_rows = (
                await ss.execute(
                    select(BotSkill, Skill)
                    .join(Skill, Skill.id == BotSkill.skill_id)
                    .where(BotSkill.bot_id.in_(bot_ids), BotSkill.enabled.is_(True))
                )
            ).all() if bot_ids else []
            skills_by_bot: dict[int, list[dict[str, Any]]] = {}
            for bs, sk in skill_rows:
                skills_by_bot.setdefault(bs.bot_id, []).append(
                    {
                        "type": sk.type,
                        "manifest": sk.manifest or {},
                        "config": bs.config or {},
                    }
                )

            async for ev in run_group_discussion(
                bots=bots,
                user_prompt=payload.prompt,
                mode=mode,
                max_rounds=max_rounds,
                mentioned=mentioned,
                attachment_context=extra_context,
                skills_by_bot=skills_by_bot,
            ):
                yield {"event": ev.type, "data": jsonlib.dumps(asdict(ev), ensure_ascii=False)}

    return EventSourceResponse(event_gen())