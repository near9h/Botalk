"""Group chat orchestration: speaker-selection policy + per-bot generation.

This replaces the earlier AgentScope MsgHub adapter with a lightweight
implementation. NewAPI is already an OpenAI-compatible gateway, so we drive
each bot directly via the `openai` SDK. Each bot replies with a synchronous
(non-streaming) completion; the orchestrator then yields one SSE
`message_start` + `message_end` pair per bot so the UI sees one bubble
appear at a time.

The "MsgHub" semantics are preserved:
  * a list of participants (bots in a group),
  * dynamic add/remove (we rebuild the list per run),
  * a speaker-selection policy decides who speaks next.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import get_settings
from app.db.models import Bot
from app.orchestrator.bots import client_for
from app.skills.resolve import build_system_context, build_tool_schemas, ensure_tools_cached, run_tool_call
from app.tools.report_schema import PAYLOAD_SCHEMA_DESCRIPTION

settings = get_settings()

# 路线 B: structured-output bots get up to this many attempts to
# produce a schema-valid JSON reply. Each attempt also slightly drops
# the temperature so the model is more likely to converge than wander.
_STRUCT_RETRY_MAX = 3


# Match bot-authored file attachments. Two flavors:
#   [FILE:foo.md] ... [/FILE]   (canonical, end-tagged)
#   [FILE:foo.md] ... (single-line, no end tag — model occasionally drops it)
# Filename must be conservative (no slashes, no colons) so we don't write
# files outside the upload dir.
_FILE_BLOCK_RE = re.compile(
    r"\[FILE:([^\]\r\n]{1,128})\]([\s\S]*?)(?:\[/FILE\]|\Z)",
    re.IGNORECASE,
)


def extract_file_blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a bot reply into (visible_text, [(filename, content), ...]).

    The visible_text has the FILE blocks removed (collapsed to a single
    "[附件: filename]" placeholder per block so the user knows what was
    authored). The caller can then persist the visible_text as the
    message and the (filename, content) pairs as Attachment rows.
    """
    blocks: list[tuple[str, str]] = []
    # Replace each match with a short notice so the chat bubble still
    # mentions what was produced (the download button also surfaces this).
    def _sub(match: "re.Match[str]") -> str:
        filename = match.group(1).strip()
        body = match.group(2)
        blocks.append((filename, body))
        return "\n\n[附件: " + filename + "]\n\n"

    cleaned = _FILE_BLOCK_RE.sub(_sub, text)
    return cleaned.strip(), blocks


@dataclass(slots=True)
class OrchestratorEvent:
    """SSE-friendly event emitted by the runner."""

    type: str  # "run_start" | "message_start" | "token" | "message_end" | "run_end" | "error"
    bot_id: int | None = None
    bot_name: str | None = None
    role: str = "bot"
    content: str = ""
    round_index: int = 0
    error: str | None = None
    # List of bot IDs that this message explicitly @-mentioned. Used by the
    # frontend to render mention chips and by the speaker policy to nudge
    # those bots to the front of the queue.
    mentions: list[int] | None = None
    # Tool-call trace (emitted as `tool_call` events when a bot invokes an
    # enabled skill tool).
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    # Attachment IDs that the chat layer persisted for this message.
    # Frontend uses this to render download buttons immediately, before
    # re-fetching the message list. Tokens are `public_id`s so URLs
    # aren't enumerable (see Attachment.public_id).
    attachments: list[str] | None = None


# ─────────────────────── speaker-selection policies ───────────────────────


class SpeakerPolicy:
    async def select(
        self,
        candidates: list[Bot],
        history: list[dict[str, str]],
        round_index: int,
    ) -> list[Bot]:
        raise NotImplementedError


class RoundRobinPolicy(SpeakerPolicy):
    async def select(self, candidates, history, round_index):
        if not candidates:
            return []
        return [candidates[round_index % len(candidates)]]


class ManualPolicy(SpeakerPolicy):
    """Yield to bots explicitly @-mentioned in the latest user message, else fall back."""

    def __init__(self, mentioned_bot_names: list[str]):
        self.mentioned = {n.lower() for n in mentioned_bot_names}

    async def select(self, candidates, history, round_index):
        if not candidates:
            return []
        if self.mentioned:
            picked = [b for b in candidates if b.name.lower() in self.mentioned]
            if picked:
                return picked
        return [candidates[round_index % len(candidates)]]


class AutoPolicy(SpeakerPolicy):
    """A rotating subset of bots speaks each round.

    For N bots and N rounds this guarantees every bot has spoken at least
    once. For very large groups we cap at AUTO_ROUND_QUOTA per round to
    avoid burning through 10×N = 60+ NewAPI calls in one discussion.
    The conversation still feels like a team discussion because the
    next round's quota rotates.
    """

    AUTO_ROUND_QUOTA = 3

    async def select(self, candidates, history, round_index):
        if not candidates:
            return []
        quota = min(self.AUTO_ROUND_QUOTA, len(candidates))
        start = (round_index * quota) % len(candidates)
        return [candidates[(start + i) % len(candidates)] for i in range(quota)]


def policy_for(mode: str, mentioned: list[str] | None = None) -> SpeakerPolicy:
    if mode == "round_robin":
        return RoundRobinPolicy()
    if mode == "manual":
        return ManualPolicy(mentioned or [])
    return AutoPolicy()


def bots_by_name_lowercase(name: str, candidates: list[Bot]) -> int | None:
    """Resolve a bot name (case-insensitive) to its ID; None if not found."""
    target = name.lower()
    for b in candidates:
        if b.name.lower() == target:
            return b.id
    return None


# ── mention extraction ────────────────────────────────────────────────
# Same pattern as the frontend's MENTION_PATTERN; keep in sync.
_MENTION_RE = re.compile(r"@([一-鿿\w][一-鿿\w·\-\d]{0,23})")


def extract_mentioned_bot_ids(text: str, candidate_bots: list[Bot]) -> list[int]:
    """Return deduped list of bot IDs whose names were @-mentioned in text."""
    names_to_id = {b.name.lower(): b.id for b in candidate_bots}
    seen: set[int] = set()
    out: list[int] = []
    for m in _MENTION_RE.finditer(text):
        key = m.group(1).lower()
        bid = names_to_id.get(key)
        if bid is not None and bid not in seen:
            seen.add(bid)
            out.append(bid)
    return out


class MentionBoostPolicy(AutoPolicy):
    """Auto mode with @-mention nudge: bots explicitly @-mentioned in the
    previous round jump to the *very first* slot of the next round, so that
    the @ is always visibly answered by the @-mentioned bot speaking first.
    Remaining quota is filled by rotating through the rest of the group."""

    def __init__(self, mentioned_ids: list[int]):
        self.mentioned_ids = mentioned_ids

    async def select(self, candidates, history, round_index):
        if not candidates:
            return []
        quota = min(self.AUTO_ROUND_QUOTA, len(candidates))
        if self.mentioned_ids:
            # 1) @-mentioned bots first (in mention order, deduped).
            front = [c for c in candidates if c.id in self.mentioned_ids]
            # 2) Everyone else, starting from the rotation offset so we
            #    don't always pick the same subset.
            rest_all = [c for c in candidates if c.id not in self.mentioned_ids]
            if not front:
                return await AutoPolicy().select(candidates, history, round_index)
            if not rest_all:
                return front[:quota]
            offset = (round_index * quota) % len(rest_all)
            rest = rest_all[offset:] + rest_all[:offset]
            return (front + rest)[:quota]
        return await AutoPolicy().select(candidates, history, round_index)


# ─────────────────────────── streaming core ───────────────────────────


def _message_text(msg: Any) -> str:
    """Extract plain text from an OpenAI chat message."""
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict)
        )
    return ""


def _tool_calls_to_messages(tool_calls: Any) -> list[dict[str, Any]]:
    """Serialize SDK tool-call objects into the OpenAI wire format."""
    out: list[dict[str, Any]] = []
    for tc in tool_calls:
        fn = getattr(tc, "function", None)
        out.append(
            {
                "id": getattr(tc, "id", None),
                "type": "function",
                "function": {
                    "name": getattr(fn, "name", ""),
                    "arguments": getattr(fn, "arguments", "{}") or "{}",
                },
            }
        )
    return out


async def _generate_agent(
    bot: Bot,
    history: list[dict[str, str]],
    client: AsyncOpenAI,
    *,
    group_members: list[Bot] | None = None,
    skills: list[dict[str, Any]] | None = None,
    on_tool_call: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    user_prompt: str | None = None,
) -> str:
    """Generate one bot reply, optionally running enabled skill tools.

    When the bot has tool/mcp skills, we run the OpenAI function-calling loop
    until the model stops requesting tool calls. Tool executions are surfaced
    to the caller via `on_tool_call` so the runner can emit `tool_call` SSE
    events, and their results are fed back as `tool` messages.
    """
    # Resolve lazy MCP skills (e.g. MCP-Marketplace) into a real tool list
    # before composing the OpenAI request. Safe no-op for non-lazy skills.
    if skills:
        for s in skills:
            await ensure_tools_cached(s, s.get("key"))

    # Cap persona length so the system prompt doesn't blow past NewAPI's
    # token budget; keep first 800 chars which usually carries the core
    # identity + responsibilities. Append a length note if we truncate.
    persona = (bot.persona or "").strip() or f"You are {bot.name}."
    if len(persona) > 800:
        persona = persona[:800] + "\n...(persona truncated)"

    # Build a roster of this group's bots so the model knows exactly which
    # @-mentions are valid. Without this, models freely invent roles
    # ("@架构师", "@项目经理") that don't exist in the group, causing the
    # next round to fall back to the default rotation instead of the
    # expected bot speaking.
    roster_lines: list[str] = []
    if group_members:
        for m in group_members:
            roster_lines.append(f"  - @{m.name} ({m.name})")
    roster_text = "\n".join(roster_lines) if roster_lines else "  (无其他成员)"

    system_content = (
        persona
        + "\n\n[格式约束] 用 Markdown 排版：1) 标题用 ## 二级、### 三级；2) 多条要点用 - 列表；3) 重点用 **加粗**；4) 代码用 ``` 包裹；5) 单次回复严格控制在 200 字以内，先结论后理由，不寒暄不重复他人。"
        + "\n\n[群成员] 本群当前有如下机器人（只能 @ 这些名字，超出列表的 @ 不会被识别、无效）：\n"
        + roster_text
        + "\n\n[协作] 如果你需要本群内某个成员配合/质疑/补充/接手，请在回复中用 @角色名 提及，例如「@项目经理 你那边排期 OK 吗」。被 @ 的成员会在下一轮优先发言。**不要 @ 不在群成员列表里的角色** —— 那种 @ 不会有任何效果。"
    )

    # Append knowledge-skill instructions + template assets so the model
    # actually follows them (e.g. the document writer's template structure).
    if skills:
        skill_context = build_system_context(skills, user_prompt=user_prompt)
        if skill_context:
            system_content += "\n\n[技能说明]\n" + skill_context
            # If any knowledge skill mentions templates, ask the bot to
            # wrap the full document body in a [FILE:foo.md]…[/FILE]
            # block so the orchestrator can save it as a downloadable
            # attachment. The outer reply stays a short summary so the
            # chat doesn't drown in duplicated content.
            has_doc_skill = any(
                ("\u6a21\u677f" in (s.get("manifest") or {}).get("instructions", ""))
                for s in skills
            )
            if has_doc_skill:
                system_content += (
                    "\n\n[\u6587\u4ef6\u9644\u4ef6] \u5982\u679c\u4f60\u6309\u6a21\u677f\u5199\u4e86\u5b8c\u6574\u6587\u6863\uff0c"
                    "**\u5fc5\u987b**\u628a\u5b8c\u6574\u5185\u5bb9\u7528\u4ee5\u4e0b\u8bed\u6cd5\u5305\u8d77\u6765\uff0c"
                    "\u4fbf\u4e8e\u524d\u7aef\u63d0\u4f9b\u4e0b\u8f7d\u6309\u94ae\uff1a\n"
                    "```\n"
                    "[FILE:report.md]\n"
                    "(\u8fd9\u91cc\u653e\u5b8c\u6574\u7684\u6587\u6863\u5185\u5bb9 \u2014\u2014 \u6807\u9898\u3001\u6b63\u6587\u3001\u5217\u8868\u90fd\u4fdd\u7559 Markdown)\n"
                    "[ENDFILE]\n"
                    "```\n"
                    "FILE \u5757**\u5916**\u53ea\u5199\u4e00\u53e5\u7b80\u77ed\u7684\u8bf4\u660e\uff08"
                    "\u4f8b\u5982\u300c\u5df2\u6309 BRD \u6a21\u677f\u751f\u6210\uff0c\u89c1\u9644\u4ef6\u300d\uff09\uff0c"
                    "\u4e0d\u8981\u628a\u540c\u4e00\u4efd\u6b63\u6587\u518d\u8d34\u4e00\u904d\u3002"
                )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content}
    ]
    for h in history:
        role = h.get("role", "user")
        if role == "assistant":
            # Tag assistant turns with the bot name so the model can tell voices apart.
            name = h.get("name") or "Assistant"
            content = h["content"]
            if len(content) > 400:
                content = content[:400] + "..."
            messages.append(
                {
                    "role": "assistant",
                    "content": f"[{name}] {content}",
                }
            )
        elif role == "user":
            messages.append({"role": "user", "content": h["content"]})

    # Use a conservative max_tokens for short chat replies; bump it up
    # for bots with document-writer skills so they can emit a full
    # document inside a [FILE:foo]…[/FILE] block. Reasoning models
    # (gemini-2.5) can otherwise spend thousands of tokens on a single
    # response even for short prompts.
    #
    # `stream=False` (synchronous): the orchestrator waits for the entire
    # reply, then emits one `message_end` with the full text. We tried
    # `stream=True` first but the resulting per-token SSE frames got
    # coalesced by nginx/uvicorn/httptools into one chunk per bot reply,
    # so the UI saw no incremental updates. Since we already collect the
    # full reply before yielding, switching to the non-streaming OpenAI
    # call removes one whole buffering layer and the UX stays the same
    # (bot bubble appears with the full reply at once).
    has_doc_skill = any(
        ("\u6a21\u677f" in (s.get("manifest") or {}).get("instructions", ""))
        for s in (skills or [])
    )
    # 路线 B：bot 的某个 skill manifest 标记了 structured_output=True，
    # 走「整条回复 = JSON payload」路径，不再下发 generate_document 工具。
    structured_doc_skill = any(
        (s.get("manifest") or {}).get("structured_output")
        for s in (skills or [])
    )

    # If the doc skill opted into structured output, inject the JSON
    # schema as a `[文档结构]` block at the end of the system prompt
    # so the model knows the exact shape we expect. We also drop the
    # `[文件附件]` prose because it's now redundant with the schema.
    if structured_doc_skill:
        system_content += (
            "\n\n[\u6587\u6863\u7ed3\u6784] \u4f60\u7684\u6574\u6761\u56de\u590d\u5fc5\u987b\u662f\u4e0b\u9762\u8fd9\u4e2a JSON schema \u7684\u552f\u4e00\u5b9e\u4f8b\u3002"
            "\u4e0d\u8981\u5305\u88f9d\u5728 ``` \u91cc\uff0c\u4e0d\u8981\u5199\u4efb\u4f55\u8bf4\u660e\u6587\u5b57\u3002\n\n"
            "```json\n" + PAYLOAD_SCHEMA_DESCRIPTION + "\n```"
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content}
    ]
    for h in history:
        role = h.get("role", "user")
        if role == "assistant":
            # Tag assistant turns with the bot name so the model can tell voices apart.
            name = h.get("name") or "Assistant"
            content = h["content"]
            if len(content) > 400:
                content = content[:400] + "..."
            messages.append(
                {
                    "role": "assistant",
                    "content": f"[{name}] {content}",
                }
            )
        elif role == "user":
            messages.append({"role": "user", "content": h["content"]})

    # Use a conservative max_tokens for short chat replies; bump it up
    # for bots with document-writer skills so they can emit a full
    # document inside a [FILE:foo]…[/FILE] block. Reasoning models
    # (gemini-2.5) can otherwise spend thousands of tokens on a single
    # response even for short prompts.
    #
    # `stream=False` (synchronous): the orchestrator waits for the entire
    # reply, then emits one `message_end` with the full text. We tried
    # `stream=True` first but the resulting per-token SSE frames got
    # coalesced by nginx/uvicorn/httptools into one chunk per bot reply,
    # so the UI saw no incremental updates. Since we already collect the
    # full reply before yielding, switching to the non-streaming OpenAI
    # call removes one whole buffering layer and the UX stays the same
    # (bot bubble appears with the full reply at once).
    params: dict = {
        "model": bot.model,
        "messages": messages,
        "temperature": float(bot.temperature),
        "max_tokens": 4096 if (has_doc_skill or structured_doc_skill) else 512,
        "stream": False,
    }
    # Pass-through any user-specified OpenAI params (top_p, frequency_penalty, …).
    for k, v in (bot.params or {}).items():
        if k in {"model", "messages", "stream"}:
            continue
        params[k] = v

    tool_schemas = build_tool_schemas(skills) if skills else []
    # 路线 B: structured doc bots don't get generate_document — they
    # emit the JSON inline and the orchestrator renders it post-hoc.
    if structured_doc_skill and tool_schemas:
        tool_schemas = [
            t for t in tool_schemas
            if t.get("function", {}).get("name") != "generate_document"
        ]
    # Ask the model for JSON mode (legacy OpenAI option, supported by
    # every OpenAI-compatible gateway). We deliberately do NOT use
    # `json_schema` strict mode — NewAPI + several upstreams reject
    # it with 400. The Pydantic schema + retry handles correctness.
    if structured_doc_skill:
        params["response_format"] = {"type": "json_object"}

    if tool_schemas:
        params["tools"] = tool_schemas

    if structured_doc_skill:
        # 路线 B retry loop: parse the reply, on ValidationError feed
        # the error back to the model and ask it to fix the JSON.
        # Up to `_STRUCT_RETRY_MAX` rounds, then fall back to whatever
        # the model produced (treated as legacy free-markdown).
        from app.tools.report_schema import parse_payload as _parse_payload
        last_err: str | None = None
        attempt = 0
        while True:
            attempt += 1
            resp = await client.chat.completions.create(**params)
            text = _message_text(resp.choices[0].message)
            try:
                payload = _parse_payload(text)
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"[:600]
                if attempt >= _STRUCT_RETRY_MAX:
                    # Give up on structured path. Return the raw text;
                    # the caller (runner) will hand it to
                    # generate_document_from_payload which falls back to
                    # legacy single-docx.
                    return text
                # Inject a corrective user message and retry.
                messages.append({"role": "assistant", "content": text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你上一条回复不是合法的 JSON。请按上面的 schema "
                            "重新生成**整条回复**为一个 JSON 对象，"
                            "不要再写解释性文字。\n\n校验错误：\n"
                            f"{last_err}"
                        ),
                    }
                )
                # Slightly cooler temperature for retries so the model
                # is more likely to converge than wander.
                params["messages"] = messages
                params["temperature"] = max(0.0, float(bot.temperature) - 0.1 * attempt)
                continue
            # Success — package the validated JSON as a canonical string
            # so downstream `generate_document_from_payload` can parse
            # it deterministically.
            return payload.model_dump_json()

    # ── legacy path (non-structured bots or old-style doc bots) ──
    resp = await client.chat.completions.create(**params)
    msg = resp.choices[0].message

    # Function-calling loop: keep calling until the model returns plain text.
    tool_rounds = 0
    while getattr(msg, "tool_calls", None) and tool_rounds < 4:
        tool_rounds += 1
        serialized = _tool_calls_to_messages(msg.tool_calls)
        messages.append(
            {"role": "assistant", "content": _message_text(msg), "tool_calls": serialized}
        )
        for tc in msg.tool_calls:
            fn = tc.function
            name = fn.name
            try:
                arguments = json.loads(fn.arguments or "{}")
                if not isinstance(arguments, dict):
                    arguments = {}
            except Exception:  # noqa: BLE001
                arguments = {}
            if on_tool_call:
                await on_tool_call(name, arguments)
            result = await run_tool_call(skills or [], name, arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": getattr(tc, "id", None),
                    "content": result,
                }
            )
        resp = await client.chat.completions.create(**params)
        msg = resp.choices[0].message

    return _message_text(msg)


# ─────────────────────────── public runner ───────────────────────────


async def run_group_discussion(
    bots: list[Bot],
    user_prompt: str,
    mode: str = "auto",
    max_rounds: int = 6,
    mentioned: list[str] | None = None,
    *,
    attachment_context: str | None = None,
    skills_by_bot: dict[int, list[dict[str, Any]]] | None = None,
    group_id: int | None = None,
) -> AsyncIterator[OrchestratorEvent]:
    """Drive a group chat discussion round by round and stream events.

    `skills_by_bot` maps bot_id → resolved skill dicts (type/manifest/config)
    for that bot's enabled skills. When present, bots get tool-calling and
    knowledge context injected into their prompts.
    """
    if not bots:
        yield OrchestratorEvent(type="run_end", error="group has no bots")
        return

    # If the caller injected parsed attachment Markdown, prepend it to the
    # user prompt so every bot sees the document context. We keep the
    # original user prompt separate in the `run_start` event.
    effective_prompt = user_prompt
    if attachment_context:
        # Soft cap to keep token usage sane (~3k tokens; PDFs can produce
        # very long Markdown). Truncate with a hint so the model knows.
        truncated = attachment_context
        ATTACHMENT_CHAR_BUDGET = 12_000
        if len(truncated) > ATTACHMENT_CHAR_BUDGET:
            truncated = (
                truncated[:ATTACHMENT_CHAR_BUDGET]
                + f"\n\n…(以下内容已截断,原文共 {len(attachment_context)} 字符)"
            )
        effective_prompt = (
            f"{user_prompt}\n\n---\n【附件内容(MinerU 解析)】\n{truncated}"
        )
    history: list[dict[str, str]] = [{"role": "user", "content": effective_prompt}]
    yield OrchestratorEvent(type="run_start", content=user_prompt, role="user")

    early_stop_markers = (
        "final answer:",
        "结论：",
        "总结：",
        "final conclusion:",
    )

    # The mention queue is refreshed after every bot reply — any @-mentioned
    # bots get a priority slot in the next round.
    pending_mentions: list[int] = []
    for m in mentioned or []:
        bid = bots_by_name_lowercase(m, bots)
        if bid is not None and bid not in pending_mentions:
            pending_mentions.append(bid)

    for round_index in range(max_rounds):
        # Pick the policy for this round. MentionBoostPolicy reorders the
        # candidate list so that any bots @-mentioned last round go first.
        if pending_mentions and mode in ("auto", "round_robin"):
            policy: SpeakerPolicy = MentionBoostPolicy(list(pending_mentions))
        else:
            policy = policy_for(mode, mentioned)
        pending_mentions = []  # consumed

        speakers = await policy.select(bots, history, round_index)
        if not speakers:
            break
        for bot in speakers:
            yield OrchestratorEvent(
                type="message_start",
                bot_id=bot.id,
                bot_name=bot.name,
                round_index=round_index,
            )
            client = client_for(bot)
            bot_skills = (skills_by_bot or {}).get(bot.id, []) if skills_by_bot else []
            tool_events: list[tuple[str, dict[str, Any]]] = []

            async def on_tool_call(name: str, args: dict[str, Any]) -> None:
                # Collect (not stream) tool calls; they're emitted below,
                # before the final `message_end`, preserving order.
                tool_events.append((name, args))

            try:
                # Synchronous generation: wait for the entire reply, then
                # emit one `message_end` with the full text. See the comment
                # in `_generate_agent` for why we dropped per-token streaming.
                full = await _generate_agent(
                    bot,
                    history,
                    client,
                    group_members=bots,
                    skills=bot_skills or None,
                    on_tool_call=on_tool_call if bot_skills else None,
                    user_prompt=user_prompt,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                err = str(exc) or exc.__class__.__name__
                yield OrchestratorEvent(
                    type="error",
                    bot_id=bot.id,
                    bot_name=bot.name,
                    error=err,
                    round_index=round_index,
                )
                history.append(
                    {
                        "role": "assistant",
                        "name": bot.name,
                        "content": f"[error: {err}]",
                    }
                )
                continue

            for tool_name, tool_args in tool_events:
                yield OrchestratorEvent(
                    type="tool_call",
                    bot_id=bot.id,
                    bot_name=bot.name,
                    round_index=round_index,
                    tool_name=tool_name,
                    tool_args=tool_args,
                )

            # 路线 B: structured doc bot's reply is a JSON payload
            # (already validated by `_generate_agent`'s retry path).
            # Hand it to the Jinja renderer and inject the resulting
            # attachment IDs into the SSE event so the UI can render
            # download buttons immediately.
            #
            # Detection is intentionally generous: we look at the
            # manifest `structured_output` flag *and* the bot's name,
            # so a stale manifest row (or a bot created by hand) still
            # benefits from 路线 B.
            structured_doc_skill = any(
                (s.get("manifest") or {}).get("structured_output")
                for s in (bot_skills or [])
            ) or bot.name in {"专业写文档", "doc_writer"}
            attachments_for_msg: list[str] = []
            if structured_doc_skill and full:
                try:
                    from app.tools.document import generate_document_from_payload
                    rendered_text, att_ids = await generate_document_from_payload(
                        full, group_id=group_id
                    )
                    if att_ids:
                        attachments_for_msg = att_ids
                    # Replace the bot's raw JSON with whatever
                    # `rendered_text` says — even when there are no
                    # attachments (parse-failure fallback). Without this
                    # the user sees the raw JSON blob in the chat
                    # bubble instead of a friendly summary.
                    if rendered_text and rendered_text != full:
                        full = rendered_text
                except Exception as exc:  # noqa: BLE001
                    # Never let a render failure crash the chat. The bot's
                    # raw JSON reply will still appear; just no attachments.
                    import logging
                    logging.getLogger(__name__).exception(
                        "render_report_payload failed for bot %s", bot.name
                    )
                    yield OrchestratorEvent(
                        type="tool_call",
                        bot_id=bot.id,
                        bot_name=bot.name,
                        round_index=round_index,
                        tool_name="render_report_payload",
                        tool_args={"error": str(exc)[:200]},
                    )

            history.append({"role": "assistant", "name": bot.name, "content": full})

            # Extract any @-mentions in this bot's reply and queue them
            # for the *next* round's priority slot.
            new_mentions = extract_mentioned_bot_ids(full, bots)
            for mid in new_mentions:
                if mid not in pending_mentions and mid != bot.id:
                    pending_mentions.append(mid)

            yield OrchestratorEvent(
                type="message_end",
                bot_id=bot.id,
                bot_name=bot.name,
                content=full,
                round_index=round_index,
                mentions=new_mentions,
                attachments=attachments_for_msg or None,
            )

        if history and any(
            marker in history[-1]["content"].lower() for marker in early_stop_markers
        ):
            break

    # ── Final pass: synthesized summary by a virtual "Summarizer" role ──
    # Skipped for very short discussions (≤ 2 bot turns) where summary is noise.
    bot_turns = [h for h in history if h.get("role") == "assistant"]
    if bot_turns and len(bot_turns) >= 2:
        yield OrchestratorEvent(
            type="message_start",
            bot_id=None,
            bot_name="📋 总结",
            round_index=max_rounds,
        )
        try:
            # Pick a model + client that the gateway will actually accept,
            # in priority order:
            #   1) The system-managed summarizer bot (固定模型 + persona,
            #      且仅一份 — 通过 uq_bots_is_system 部分唯一索引保证),
            #   2) settings.orchestrator_model if explicitly configured,
            #   3) The first bot in this group (guaranteed routable since
            #      it just succeeded in the same run),
            #   4) Hardcoded fallback so we never crash with NameError.
            from app.db.session import SessionLocal
            from app.db.models import Bot as BotModel
            from sqlalchemy import select as _select

            summary_client = client_for(bots[0])
            summary_model = bots[0].model or "gpt-4o-mini"
            try:
                async with SessionLocal() as _s:
                    _row = (
                        await _s.execute(
                            _select(BotModel).where(BotModel.is_system.is_(True))
                        )
                    ).scalar_one_or_none()
                    if _row is not None:
                        summary_client = client_for(_row)
                        summary_model = _row.model or summary_model
            except Exception:  # noqa: BLE001
                # DB hiccup must not kill the whole summary pass.
                pass
            override = (
                settings.orchestrator_model.strip()
                if getattr(settings, "orchestrator_model", None)
                else ""
            )
            if override:
                summary_model = override
            summary = await _summarize(
                summary_client,
                user_prompt,
                bot_turns,
                model=summary_model,
            )
            history.append({"role": "assistant", "name": "📋 总结", "content": summary})
            yield OrchestratorEvent(
                type="message_end",
                bot_id=None,
                bot_name="📋 总结",
                content=summary,
                round_index=max_rounds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield OrchestratorEvent(
                type="error",
                bot_id=None,
                bot_name="📋 总结",
                error=str(exc) or exc.__class__.__name__,
                round_index=max_rounds,
            )

    yield OrchestratorEvent(type="run_end")


async def _summarize(
    client: AsyncOpenAI,
    user_prompt: str,
    bot_turns: list[dict[str, str]],
    *,
    model: str,
) -> str:
    """Ask the gateway for a structured Markdown summary of the discussion."""
    transcript_lines: list[str] = []
    for h in bot_turns:
        name = h.get("name", "Bot")
        content = h.get("content", "")
        if len(content) > 600:
            content = content[:600] + "..."
        transcript_lines.append(f"[{name}] {content}")
    transcript = "\n\n".join(transcript_lines)

    system = (
        "你是一位资深会议纪要官。请基于下方多角色讨论记录，输出结构化 Markdown 总结。"
        "要求："
        "1) 先写一句 TL;DR（结论先行，50 字以内）；"
        "2) 用 ## 共识、## 分歧、## 行动项 三段式（无内容可写'无'）；"
        "3) 每个行动项写明建议负责人角色；"
        "4) 严格 200 字以内；"
        "5) 用中文。"
    )
    user = f"【用户问题】\n{user_prompt}\n\n【讨论记录】\n{transcript}"
    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
        "stream": False,
    }
    resp = await client.chat.completions.create(**params)
    try:
        choices = resp.choices
        msg = choices[0].message
        content = msg.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    except Exception:
        pass
    return "（总结生成失败）"


_ = json  # re-exported in case callers want raw event dumps later