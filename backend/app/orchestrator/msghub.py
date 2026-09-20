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
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Bot
from app.orchestrator.bots import client_for
from app.services import rag_retriever
from app.services.language_detect import detect_response_language
from app.skills.resolve import build_system_context, build_tool_schemas, ensure_tools_cached, run_tool_call
from app.tools.report_schema import PAYLOAD_SCHEMA_DESCRIPTION

settings = get_settings()

# 路线 B: structured-output bots get up to this many attempts to
# produce a schema-valid JSON reply. Each attempt also slightly drops
# the temperature so the model is more likely to converge than wander.
_STRUCT_RETRY_MAX = 3


def _now_iso() -> str:
    """UTC ISO timestamp with no microseconds — what we send over SSE.

    Stable on the wire so the chat UI can group events into a single
    bubble even when one round produces several `message_end` payloads.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    # Attachment metadata that the chat layer persisted for this
    # message. Each entry is shaped like AttachmentMeta on the
    # frontend ({public_id, filename, mime_type, size_bytes, source})
    # so the bubble can render the download card inline. Frontend
    # also accepts legacy integer-id lists for backward compat.
    attachments: list[Any] | None = None
    # Knowledge-base citations surfaced alongside this message. Each
    # entry is a dict shaped for the frontend SourceCitation chip:
    #   {chunk_id, kb_id, kb_doc_id, filename, page, para, bbox,
    #    snippet, score, ragflow_chunk_id}
    # Empty list when the bot has no KB mounted or retrieval returned
    # nothing — never None so the SSE consumer can iterate freely.
    cited_refs: list[dict[str, Any]] | None = None
    # ISO timestamp of when this event was produced. The chat UI
    # stamps every bubble on `message_end` and stamps the user prompt
    # on `run_start` so the user can see when each reply landed and
    # so the "重试" button knows which user prompt to re-send.
    created_at: str | None = None


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
    kb_session: AsyncSession | None = None,
    kb_query: str | None = None,
    policy_block: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Generate one bot reply, optionally running enabled skill tools.

    When the bot has tool/mcp skills, we run the OpenAI function-calling loop
    until the model stops requesting tool calls. Tool executions are surfaced
    to the caller via `on_tool_call` so the runner can emit `tool_call` SSE
    events, and their results are fed back as `tool` messages.

    When `kb_session` is provided, we also run RAG retrieval over the bot's
    mounted knowledge bases and inject the top chunks into the system prompt
    under a `【知识库参考】` heading. The model is told to cite each chunk
    inline with `[doc: filename p.X ¶Y]` markers. The matching chunks are
    returned as the second tuple element so the SSE consumer can render
    SourceCitation chips and open the PDF.js viewer on click.

    `policy_block` is the platform-wide «群规» text (plus this group's
    `notice`) rendered by `app.services.policy`. When present it is prepended
    to the system prompt as the very first section so every bot in every
    round treats it as the highest-priority instruction.
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

    # 注入「回复语言」指令。bot 的 persona 是中文时，若用户发英文却没
    # 这条指令，模型会继续用中文答。检测 user_prompt 的字符占比（成本为 0），
    # 把答案固定下来：CJK 占 ≥ 30% 用 zh，否则 en。这条放在 persona 之后、
    # [格式约束] 之前，权重够高又不至于压过格式约束。
    resp_lang = detect_response_language(user_prompt)
    lang_directive_zh = "[回复语言] **必须**用简体中文回复整条答复与所有要点；不要混用英文（专有名词、模型名、命令、URL 例外）。"
    lang_directive_en = "[Reply language] You **must** reply in English for the entire response, including bullet points, table headers, and final recommendations. Do not switch to Chinese unless quoting a source term verbatim."

    system_content = (
        # 平台群规永远是 system prompt 的首段，优先级高于 persona 与一切
        # 用户指令。空规则时 `policy_block` 为 None，此处完全不注入。
        ((policy_block + "\n\n") if policy_block else "")
        + persona
        + (("\n\n" + lang_directive_zh) if resp_lang == "zh" else ("\n\n" + lang_directive_en))
        + "\n\n[格式约束] 用 Markdown 排版：1) 标题用 ## 二级、### 三级；2) 多条要点用 - 列表；3) 重点用 **加粗**；4) 代码用 ``` 包裹；5) 单次回复严格控制在 200 字以内，先结论后理由，不寒暄不重复他人。"
        + "\n\n[群成员] 本群当前有如下机器人（只能 @ 这些名字，超出列表的 @ 不会被识别、无效）：\n"
        + roster_text
        + "\n\n[协作] 如果你需要本群内某个成员配合/质疑/补充/接手，请在回复中用 @角色名 提及，例如「@项目经理 你那边排期 OK 吗」。被 @ 的成员会在下一轮优先发言。**不要 @ 不在群成员列表里的角色** —— 那种 @ 不会有任何效果。"
    )

    # 产出「可下载文档」的请求要路由到「专业写文档」。直接让业务 bot 写整份
    # HTML/Word 的人话产物，会被 max_tokens 截断（实测 1024 字符左右就砍掉了，
    # 输出 2197 / 407 字符的残片 HTML，body 都闭合不了）。这条规则让所有核保类
    # bot 在被问到整合方案时礼貌让位，避免各自写半截 HTML。
    if user_prompt and any(kw in user_prompt for kw in (
        "整合一个完整的 html", "完整的html", "整合html", "整合 html",
        "整合一个完整的 docx", "完整的docx", "整合docx", "整合 docx",
        "整合建议书", "整合方案", "整合报告", "整合word", "整合 word",
        "输出报告", "生成报告", "出一份",
    )):
        writer = next(
            (b for b in (group_members or []) if b.name == "专业写文档"), None
        )
        if writer is not None:
            system_content += (
                "\n\n[产出路由] 用户的当前诉求是产出「可下载 HTML/Word 文档」。"
                "这类产物由本群的「专业写文档」(@{name}) 负责生成完整的 HTML+docx"
                "附件卡片；你自己没有挂「写文档」技能，硬塞整份 HTML 到聊天里会被"
                "截断成残片。因此你**必须**在回复里：\n"
                "  1) 简述你对该方案的核心结论（2-3 句话即可，不要再贴任何 ```html 围栏或 JSON schema）；\n"
                "  2) 在末尾 @专业写文档 并明确交代输入要素（例如「基于上面三轮核保意见与外部信息官"
                "搜集的最新信息，整合成完整 HTML+docx 提案书」），由它在下一轮生成附件卡片。\n"
                "**不要**自己写 ```html 或 [FILE:...] 长文档块 —— 交给专业写文档。".format(
                    name=writer.name
                )
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

    # ── RAG retrieval (Stage 3) ──
    # Pull chunks from every KB mounted on this bot, optionally rerank
    # via GLM, and inject the top-N into the system prompt as
    # `【知识库参考】`. The chunk list is returned alongside the reply so
    # the SSE consumer can render SourceCitation chips.
    #
    # The retrieval step is wrapped in try/except so a broken RAGFlow
    # never crashes the chat — we just emit the bot's plain reply
    # without citations.
    cited_refs: list[dict[str, Any]] = []
    if kb_session is not None and kb_query:
        try:
            retrieval = await rag_retriever.retrieve_for_bot(
                bot.id, kb_query, kb_session,
            )
            if retrieval.context_block:
                system_content += "\n\n" + retrieval.context_block
            cited_refs = [
                {
                    "chunk_id": c.chunk_id,
                    "kb_id": c.kb_id,
                    "kb_doc_id": c.kb_doc_id,
                    "filename": c.document_name,
                    "page": c.page,
                    "para": c.para,
                    "bbox": c.bbox,
                    "snippet": c.snippet,
                    "score": c.score,
                    "ragflow_chunk_id": c.ragflow_chunk_id,
                    "citation_key": c.citation_key,
                }
                for c in retrieval.chunks
            ]
        except Exception as exc:  # noqa: BLE001
            # Retrieval must NEVER abort a chat. Log and proceed without
            # KB context — the LLM will answer from its base knowledge
            # and the user just won't see citations for this turn.
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "KB retrieval failed for bot %s: %s", bot.id, exc,
            )
            cited_refs = []

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
    # KB-grounded bots need a generous output budget: the model
    # often summarizes 3-5 chunks into a structured answer and
    # previously hit the 512 cap mid-sentence. 2048 keeps room for
    # citation markers + an occasional quoted clause from a chunk; we
    # still truncate hard at 4096 for doc-skill bots that emit full
    # reports.
    #
    # 2026-09-20: 把默认上限从 1024 提到 2048。MiniMax-M3 在 1024 上回
    # 吐「整合一个完整的 html」请求时，断在 `<style>` CSS 中间且不带
    # 闭合（2205 / 407 字符），造成 iframe 渲染出空白页。
    # 同时检测用户的 deliverable 请求：它在 prompt 模板里会被劝去
    # @专业写文档，但有时模型还是会尝试硬塞整份 HTML。给这种 bot 一个
    # 临时 8192 token 的余地，免得触发「模型撞墙输出残片」的退化。
    user_wants_html_doc = bool(user_prompt) and any(
        kw in user_prompt for kw in (
            "整合一个完整的 html", "完整的html", "整合html", "整合 html",
            "整合一个完整的 docx", "完整的docx", "整合docx", "整合 docx",
            "整合建议书", "整合方案", "整合报告", "整合word", "整合 word",
            "输出报告", "生成报告", "出一份",
        )
    )
    if (has_doc_skill or structured_doc_skill):
        max_tokens = 4096
    elif user_wants_html_doc:
        max_tokens = 8192
    else:
        max_tokens = 2048
    params: dict = {
        "model": bot.model,
        "messages": messages,
        "temperature": float(bot.temperature),
        "max_tokens": max_tokens,
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
                    return text, cited_refs
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
            return payload.model_dump_json(), cited_refs

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

    # Posthoc substring-match citation injection. The LLM is *asked*
    # to write `[N]` / `[doc: …]` markers in the prompt, but in practice
    # it often paraphrases or forgets. The inject_markers pass below
    # scans the LLM reply for verbatim chunks (and falls back to a
    # 15-char overlap match for paraphrased content), then inserts
    # `[doc: <key>]` markers at the next sentence boundary after each
    # hit. It runs whenever the answer has KB refs to attribute.
    text = _message_text(msg)
    if cited_refs and text and not structured_doc_skill:
        try:
            from app.services.citation_aligner import inject_markers
            text = inject_markers(text, cited_refs, [])
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "citation alignment failed for bot %s: %s", bot.id, exc
            )
    # 调一次 finish_reason：区分「撞 max_tokens」与「模型主动刹车」。前者要把
    # 那一类的 max_tokens 提上去；后者多半是 prompt 给了「短回复」硬约束，模型在
    # 自觉遵守 —— 两条修法完全不同。命中 length 时打 WARNING（这种回复会被前
    # 端截断渲染成残片，是用户可见的退化）。
    try:
        finish_reason = getattr(getattr(resp, "choices", [None])[0], "finish_reason", None)
        if finish_reason == "length":
            logging.getLogger(__name__).warning(
                "bot %s reply truncated by max_tokens (chars=%d)",
                bot.id, len(text),
            )
        else:
            logging.getLogger(__name__).debug(
                "bot %s reply finish_reason=%s chars=%d",
                bot.id, finish_reason, len(text),
            )
    except Exception:
        pass
    return text, cited_refs


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
    policy_block: str | None = None,
    prior_history: list[dict[str, str]] | None = None,
) -> AsyncIterator[OrchestratorEvent]:
    """Drive a group chat discussion round by round and stream events.

    `skills_by_bot` maps bot_id → resolved skill dicts (type/manifest/config)
    for that bot's enabled skills. When present, bots get tool-calling and
    knowledge context injected into their prompts.

    `policy_block` is the pre-rendered platform «群规» (+ this group's notice)
    text from `app.services.policy.build_policy_block`. The caller computes it
    **once per request** so every bot and every round sees the identical text.

    `prior_history` is the already-trimmed transcript of earlier turns in the
    **same task** (`[{"role": "user"|"assistant", "name": ..., "content": ...}]`).
    The caller loads and budgets it; we only splice it in front of this turn.
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
    # 同一 task 的历史轮次先铺进来，再接本次提问。追问会复用同一个 run，不回灌
    # 的话模型只看得到孤零零的这一句：用户先要「整合一个完整的 html」、再追问
    # 「html呢」，各 bot 集体回「HTML 不属于我的领域」，就是缺了这段前情。
    # 裁剪与预算由调用方负责（见 api/chat._load_prior_history）。
    seeded = len(prior_history or [])
    history: list[dict[str, str]] = list(prior_history or [])
    history.append({"role": "user", "content": effective_prompt})
    yield OrchestratorEvent(type="run_start", content=user_prompt, role="user", created_at=_now_iso())

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
                #
                # Stage 3: open a short-lived session for RAG retrieval.
                # `_generate_agent` will pull chunks from every KB mounted
                # on `bot` and emit citation metadata. We don't keep the
                # session open across the LLM call — RAGFlow + GLM
                # network calls dominate anyway, and an extra long-lived
                # session just holds idle connections.
                from app.db.session import SessionLocal as _SessionLocal
                async with _SessionLocal() as _kb_session:
                    full, cited_refs = await _generate_agent(
                        bot,
                        history,
                        client,
                        group_members=bots,
                        skills=bot_skills or None,
                        on_tool_call=on_tool_call if bot_skills else None,
                        user_prompt=user_prompt,
                        kb_session=_kb_session,
                        kb_query=user_prompt,
                        policy_block=policy_block,
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
            attachments_for_msg: list[dict[str, Any]] = []
            if structured_doc_skill and full:
                try:
                    from app.tools.document import generate_document_from_payload
                    rendered_text, att_ids = await generate_document_from_payload(
                        full, group_id=group_id
                    )
                    # att_ids is now a list of AttachmentMeta dicts so the
                    # chat bubble can render the download card inline
                    # without a second batch-meta round-trip.
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
                # Stage 3: forward KB citation metadata. Empty list when
                # the bot has no KB mounted or retrieval returned nothing.
                cited_refs=cited_refs,
                created_at=_now_iso(),
            )

        if history and any(
            marker in history[-1]["content"].lower() for marker in early_stop_markers
        ):
            break

    # ── Final pass: synthesized summary by a virtual "Summarizer" role ──
    # Skipped for very short discussions (≤ 2 bot turns) where summary is noise.
    # 只看**本次** run 的发言：带上历史种子的话，一是会把上一轮的内容也总结进去，
    # 二是「≥2 条 bot 发言」这个门槛会被历史立刻满足，每问一句都多出一条总结。
    bot_turns = [h for h in history[seeded:] if h.get("role") == "assistant"]
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
                policy_block=policy_block,
            )
            history.append({"role": "assistant", "name": "📋 总结", "content": summary})
            yield OrchestratorEvent(
                type="message_end",
                bot_id=None,
                bot_name="📋 总结",
                content=summary,
                round_index=max_rounds,
                # The summarizer never goes through the RAG pipeline,
                # but we send `cited_refs=[]` so the frontend's data
                # shape is uniform across bot turns and the summary
                # (no undefined-vs-empty ambiguity).
                cited_refs=[],
                created_at=_now_iso(),
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
    policy_block: str | None = None,
) -> str:
    """Ask the gateway for a structured Markdown summary of the discussion.

    `policy_block` (when present) is prepended to the summary's own system
    prompt so the generated 纪要 also obeys the platform «群规» — the summary
    is user-visible output, so it must not be the one place rules are ignored.

    回复语种与用户输入语种保持一致 —— 不然中文 bot 在英文群里答中文，
    最后一段中文纪要就破坏了整轮对话的语种一致性（之前已对每个
    bot turn 做过语种跟随；纪要是最后一段，不能漏）。
    """
    transcript_lines: list[str] = []
    for h in bot_turns:
        name = h.get("name", "Bot")
        content = h.get("content", "")
        if len(content) > 600:
            content = content[:600] + "..."
        transcript_lines.append(f"[{name}] {content}")
    transcript = "\n\n".join(transcript_lines)

    # 复用与 bot turn 同样的启发式（见 services/language_detect）。
    # 之所以不传 `user_prompt` 整个：里面包含附件 Markdown、@提及、群规
    # 之外的「多话」片段，对语种判定的信号被稀释。`user_prompt` 是
    # original user text，足够代表用户意图。
    resp_lang = detect_response_language(user_prompt)
    if resp_lang == "zh":
        system = (
            ((policy_block + "\n\n") if policy_block else "")
            + "你是一位资深会议纪要官。请基于下方多角色讨论记录，输出结构化 Markdown 总结。"
            "要求："
            "1) 先写一句 TL;DR（结论先行，50 字以内）；"
            "2) 用 ## 共识、## 分歧、## 行动项 三段式（无内容可写'无'）；"
            "3) 每个行动项写明建议负责人角色；"
            "4) 严格 200 字以内；"
            "5) **必须用简体中文**回复整条纪要（包括标题与行动项条目）。"
        )
    else:
        system = (
            ((policy_block + "\n\n") if policy_block else "")
            + "You are a senior meeting minute-taker. Based on the multi-role "
            "discussion below, output a structured Markdown summary."
            "Requirements:"
            "1) Lead with a TL;DR (≤50 words, conclusions first);"
            "2) Use three sections: ## Consensus, ## Disagreements, ## Action Items "
            "(write 'None' for empty sections);"
            "3) Each action item must specify a suggested owner role;"
            "4) Stay under 200 words;"
            "5) **Reply entirely in English** for the entire summary, including "
            "section headers and action items."
        )
    user = f"【用户问题 / User question】\n{user_prompt}\n\n【讨论记录 / Discussion transcript】\n{transcript}"
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