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
from app.db.models import Attachment, Bot, BotSkill, Group, Message, Run, User  # noqa: F811
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
from app.services.policy import build_policy_block

router = APIRouter()
settings = get_settings()

_MENTION_RE = re.compile(r"@([\w一-鿿]+)")

# 同一 task 前情回灌的预算：条数 + 字符数双上限。一次 HTML/报表类回复就能有
# 几千字符，只按条数限制挡不住上下文膨胀，所以两个上限都要有。
_HISTORY_MAX_MESSAGES = 20
_HISTORY_MAX_CHARS = 6000


def _extract_mentions(prompt: str) -> list[str]:
    return _MENTION_RE.findall(prompt)


async def _load_prior_history(session: AsyncSession, run_id: int) -> list[dict[str, str]]:
    """取同一 task 里已有的消息，作为新一问的前情。

    同一 task 的多轮追问复用同一个 run（前端带 task_token），但每次调用
    `run_group_discussion` 都是一张白纸 —— 用户先要「整合一个完整的 html」、
    紧接着追问「html呢」，如果只看得到「html呢」，各 bot 只能集体答非所问。

    从最近一条往回收集，用完条数或字符预算为止，再翻回正序：越近的轮次越
    重要，预算不够时优先保留它们。
    """
    rows = (
        await session.execute(
            select(Message, Bot.name)
            .outerjoin(Bot, Bot.id == Message.bot_id)
            .where(Message.run_id == run_id)
            .order_by(Message.id.desc())
            .limit(_HISTORY_MAX_MESSAGES)
        )
    ).all()
    picked: list[dict[str, str]] = []
    used = 0
    for msg, bot_name in rows:
        content = (msg.content or "").strip()
        if not content:
            continue
        # 已经收到东西了才允许因超预算而停，否则单条超长消息会被整条丢掉。
        if picked and used + len(content) > _HISTORY_MAX_CHARS:
            break
        if msg.role == "user":
            picked.append({"role": "user", "content": content})
        else:
            # 库里存的是 "bot"；`_generate_agent` 只认 user/assistant，其余角色
            # 会被静默丢弃，所以这里统一映射，并带上发言人名字（它会把名字
            # 拼回 `[name] ...`，让模型能分辨不同 bot 的声音）。
            picked.append(
                {
                    "role": "assistant",
                    "name": bot_name or "助手",
                    "content": content,
                }
            )
        used += len(content)
    picked.reverse()
    return picked


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
    # `payload.attachment_ids` carries the public share_token (32-char
    # URL-safe string), so we have to map back to the integer PK before
    # filtering. Empty/None means no extra attachments.
    extra_ctx_parts: list[str] = []
    if payload.attachment_ids:
        # Don't trust client-supplied attachment ids blindly — only inject
        # Markdown from attachments whose parent group the caller can see.
        atts = (
            await session.execute(
                select(Attachment).where(
                    Attachment.public_id.in_(payload.attachment_ids)
                )
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
    # 先把同 task 的历史取出来，再写本次提问 —— 顺序反了就会把刚存进去的这一句
    # 也算成「前情」，模型会看到自己的问题重复一遍。新 task 这里自然是空列表。
    prior_history = await _load_prior_history(session, run.id)
    # Persist the user turn immediately so /api/messages returns it on
    # page refresh. Before this, `run_start` only existed in the SSE
    # stream — refreshing the page dropped the user's prompt from view
    # because nothing had written a `role='user'` row yet.
    if payload.prompt:
        try:
            await save_message(
                session,
                run_id=run.id,
                group_id=group_id_int,
                role="user",
                content=payload.prompt,
                attachments=payload.attachment_ids,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[chat] save user_message failed: {exc}")

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

            # 平台「群规 / 防火墙规则」+ 本群 notice，渲染成一段文本。
            # 每个请求只算一次，保证同一次讨论内每个 bot、每一轮看到的
            # 规则完全一致（也避免逐轮重复查库）。
            policy_block = await build_policy_block(ss, group)

            async for ev in run_group_discussion(
                bots=bots,
                user_prompt=payload.prompt,
                mode=mode,
                max_rounds=max_rounds,
                mentioned=mentioned,
                attachment_context=extra_context,
                skills_by_bot=skills_by_bot,
                group_id=group_id_int,
                policy_block=policy_block,
                prior_history=prior_history,
            ):
                # Persist every user/bot message into chat so the
                # history list shows attachments the bot produced
                # (routes B's `attachments: list[str]` of public_ids
                # → JSON column).
                if ev.type == "message_end" and ev.content:
                    try:
                        await save_message(
                            ss,
                            run_id=run.id,
                            group_id=group_id_int,
                            role=ev.role or "bot",
                            content=ev.content,
                            bot_id=ev.bot_id,
                            # ev.attachments already carries public_ids
                            # (see generate_document_from_payload); keep
                            # them as-is so /api/messages and the SSE
                            # payload match the URL convention.
                            attachments=ev.attachments or None,
                            # Stage 3: persist RAG citation metadata so
                            # /api/messages can re-render citations on
                            # refresh without re-running retrieval.
                            cited_refs=ev.cited_refs or None,
                        )
                    except Exception as exc:  # noqa: BLE001
                        # Never let persistence failures break the
                        # stream; the SSE event still goes out and
                        # the UI will refetch on next refresh.
                        print(f"[chat] save_message failed: {exc}")
                yield {"event": ev.type, "data": jsonlib.dumps(asdict(ev), ensure_ascii=False)}

    return EventSourceResponse(event_gen())