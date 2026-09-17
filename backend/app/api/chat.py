"""Streaming chat (SSE) endpoint."""
import asyncio
import json as jsonlib
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.db.models import Attachment, BotSkill  # noqa: F811
from app.db.session import get_session
from app.orchestrator.msghub import run_group_discussion
from app.orchestrator.runner import (
    finish_run,
    get_bots_in_order,
    get_group_with_members,
    save_message,
    start_run,
)
from app.schemas import ChatRequest

router = APIRouter()
settings = get_settings()

_MENTION_RE = re.compile(r"@([\w一-鿿]+)")


def _extract_mentions(prompt: str) -> list[str]:
    return _MENTION_RE.findall(prompt)


@router.post("/stream")
async def stream_chat(
    payload: ChatRequest, session: AsyncSession = Depends(get_session)
) -> EventSourceResponse:
    group = await get_group_with_members(session, payload.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    bots = await get_bots_in_order(session, group)
    if not bots:
        raise HTTPException(status_code=400, detail="group has no bots")

    mode = payload.mode or group.mode
    max_rounds = payload.max_rounds or group.max_rounds or settings.default_max_rounds
    mentioned = _extract_mentions(payload.prompt)

    # Resolve attachments → concatenated Markdown context (if any).
    attachment_context: str | None = None
    if payload.attachment_ids:
        result = await session.execute(
            select(Attachment).where(Attachment.id.in_(payload.attachment_ids))
        )
        atts = result.scalars().all()
        if atts:
            parts: list[str] = []
            for a in atts:
                if a.status != "done":
                    continue
                parts.append(
                    f"### 附件:{a.filename}\n\n{a.content_md or ''}"
                )
            if parts:
                attachment_context = "\n\n---\n\n".join(parts)

    # Resolve each bot's enabled skills (with per-bot config) so the
    # orchestrator can inject knowledge context + tool schemas.
    skills_by_bot: dict[int, list[dict]] = {}
    skill_result = await session.execute(
        select(BotSkill)
        .options(selectinload(BotSkill.skill))
        .where(BotSkill.bot_id.in_([b.id for b in bots]), BotSkill.enabled.is_(True))
    )
    for bs in skill_result.scalars().all():
        skills_by_bot.setdefault(bs.bot_id, []).append(
            {
                "key": bs.skill.key,
                "type": bs.skill.type,
                "manifest": bs.skill.manifest or {},
                "config": bs.config or {},
            }
        )

    run = await start_run(session, payload.group_id, payload.prompt)

    # SSE responses need explicit no-cache + no-buffering headers. Without
    # them, intermediate proxies (and even some browsers via fetch + reader)
    # will hold the whole stream until it closes, so the UI only updates once
    # `run_end` fires (or after the user refreshes and reloads from DB).
    sse_headers = {
        # Disable all caching/intermediaries transforming the stream.
        "Cache-Control": "no-cache, no-transform",
        # Tell nginx (and any other reverse proxy) to NOT buffer.
        "X-Accel-Buffering": "no",
    }

    async def event_generator():
        # Persist user message first.
        user_msg = await save_message(
            session,
            run_id=run.id,
            group_id=payload.group_id,
            role="user",
            content=payload.prompt,
        )
        yield {
            "event": "user_message",
            "data": jsonlib.dumps({"id": user_msg.id, "content": payload.prompt}),
        }
        await asyncio.sleep(0)

        total_tokens = 0
        last_status = "done"
        try:
            async for ev in run_group_discussion(
                bots=bots,
                user_prompt=payload.prompt,
                mode=mode,
                max_rounds=max_rounds,
                mentioned=mentioned,
                attachment_context=attachment_context,
                skills_by_bot=skills_by_bot,
            ):
                if ev.type == "message_end" and ev.content:
                    try:
                        # Split bot-authored [FILE:foo.md]…[/FILE] blocks
                        # out of the reply so we can save them as
                        # downloadable attachments. The visible_text we
                        # store on the message keeps a "[附件: foo.md]"
                        # placeholder so the chat bubble stays readable.
                        from app.orchestrator.msghub import extract_file_blocks

                        visible_text, file_blocks = extract_file_blocks(ev.content)
                        att_ids: list[int] = []
                        inserted_attachments: list[Attachment] = []
                        for fname, body in file_blocks:
                            # Use a permissive text mime — bots may emit
                            # markdown, plain text, CSV, etc.
                            mime = "text/markdown"
                            if fname.lower().endswith((".txt", ".log")):
                                mime = "text/plain"
                            elif fname.lower().endswith(".csv"):
                                mime = "text/csv"
                            elif fname.lower().endswith(".json"):
                                mime = "application/json"
                            elif fname.lower().endswith((".html", ".htm")):
                                mime = "text/html"
                            att = Attachment(
                                group_id=payload.group_id,
                                bot_id=ev.bot_id,
                                source="bot",
                                filename=fname,
                                mime_type=mime,
                                size_bytes=len(body.encode("utf-8")),
                                status="done",
                                content_md=body,
                                storage_path=None,
                            )
                            session.add(att)
                            await session.flush()  # populate att.id
                            att_ids.append(att.id)
                            inserted_attachments.append(att)
                        # Build the metadata the UI needs to render a nice
                        # download card (filename + size + mime) without a
                        # second round-trip. `session.new` empties after
                        # flush(), so we keep our own list of inserted
                        # Attachment objects and read their attrs now
                        # (att.id, att.filename etc. are populated by
                        # flush() and won't change on commit).
                        att_meta: list[dict] = []
                        for att in inserted_attachments:
                            att_meta.append({
                                "id": att.id,
                                "filename": att.filename,
                                "mime_type": att.mime_type,
                                "size_bytes": att.size_bytes,
                                "source": att.source,
                            })
                        msg = await save_message(
                            session,
                            run_id=run.id,
                            group_id=payload.group_id,
                            role="bot",
                            content=visible_text or ev.content,
                            bot_id=ev.bot_id,
                        )
                        # Link the attachments to the message.
                        if att_ids:
                            msg.attachments = list(att_ids)
                            await session.commit()
                            await session.refresh(msg)
                        # Tell the UI what was produced so the bubble can
                        # render download buttons immediately. Pass full
                        # metadata so the bubble doesn't need a second
                        # round-trip to know filename/size.
                        ev.attachments = att_meta
                    except Exception as save_exc:  # noqa: BLE001
                        # Don't let a DB hiccup kill the whole stream.
                        yield {
                            "event": "error",
                            "data": jsonlib.dumps(
                                {"error": f"save_message failed: {save_exc}"}
                            ),
                        }
                        await asyncio.sleep(0)
                payload_dict = {
                    "type": ev.type,
                    "bot_id": ev.bot_id,
                    "bot_name": ev.bot_name,
                    "content": ev.content,
                    "round_index": ev.round_index,
                    "error": ev.error,
                    "mentions": ev.mentions,
                    "tool_name": ev.tool_name,
                    "tool_args": ev.tool_args,
                    "attachments": ev.attachments,
                }
                yield {"event": ev.type, "data": jsonlib.dumps(payload_dict)}
                # Yield to the event loop so uvicorn flushes this SSE
                # event to the socket immediately. Without this, httptools'
                # write buffer can hold small events (a single `token`
                # chunk is just a few bytes) until enough data accumulates
                # or the response ends — making the browser see nothing
                # until `run_end` and forcing a manual page refresh.
                await asyncio.sleep(0)
                if ev.type == "error":
                    last_status = "error"
        except Exception as exc:  # noqa: BLE001
            last_status = "error"
            yield {
                "event": "error",
                "data": jsonlib.dumps({"error": str(exc)}),
            }
            await asyncio.sleep(0)

        try:
            await finish_run(session, run.id, last_status, total_tokens)
        except Exception:  # noqa: BLE001
            pass
        yield {"event": "run_end", "data": jsonlib.dumps({"run_id": run.id})}
        await asyncio.sleep(0)

    # `ping=15` keeps idle connections from being killed by intermediate
    # proxies that drop "idle" TCP connections after ~30s. Combined with the
    # `Cache-Control` / `X-Accel-Buffering` headers above, this guarantees
    # each token reaches the browser as soon as the upstream LLM yields it.
    return EventSourceResponse(
        event_generator(),
        headers=sse_headers,
        ping=15,
    )