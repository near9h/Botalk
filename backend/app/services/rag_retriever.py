"""Bot-aware RAG retrieval: pulls chunks from mounted knowledge bases,
optionally re-ranks them with GLM, and returns the slice of metadata
the chat orchestrator needs to inject into the LLM prompt.

Pipeline:

    retrieve_for_bot(bot_id, query)
      │
      ├─ look up bot_kb → KB ids the bot has mounted
      ├─ local_retriever.retrieve(bot_id, query) → pgvector cosine hits
      ├─ (optional) GLM rerank(query, snippets) → top_n_after_rerank
      └─ convert hits → RetrievedChunk so the chat UI can light up
         the PDF.js overlay.

The local vector store lives in Postgres (pgvector) and is populated by
`ingest_worker.embed_chunks_for_doc`. The legacy RAGFlow path is kept
around as a no-op fallback for KB rows that already carry a
`ragflow_dataset_id`, but new KBs flow through pgvector exclusively.

Why a separate module rather than inlining in `msghub.py`:
  - It owns its own DB session lifecycle and isolates network failures
    (GLM quota exhausted) so the chat path can degrade gracefully and
    still emit a normal answer.
  - The chunk metadata mapping (hit dict → RetrievedChunk) is dense
    and benefits from its own dataclass + helpers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services import local_retriever, zhipuai_embed

logger = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────── result types ───────────────────────────


@dataclass(slots=True)
class RetrievedChunk:
    """One retrieval hit ready for prompt injection + UI rendering.

    Fields map 1:1 to what `msghub._generate_agent` writes into the
    `[doc: filename p.X ¶Y]` citation markers and what the chat SSE
    `cited_refs` array carries to the frontend.
    """

    # Prompt-side identifier — stable across the LLM call so the model
    # can echo it back inside its answer text.
    citation_key: str
    # UI-side identifier — lets the chat client request
    # `GET /api/kb/{public_id}/chunks/{chunk_id}` for the bbox payload.
    chunk_id: int
    # Wire-facing KB token (matches `KnowledgeBase.public_id`). The
    # chat SSE consumer uses this directly; switching to public_id
    # means a citation chip doesn't leak the integer pk.
    kb_id: str
    kb_doc_id: int
    document_name: str  # filename as shown to the user
    page: int | None
    para: int | None
    bbox: list | None  # [x1, y1, x2, y2]
    snippet: str  # snippet text (truncated to ~200 chars in snippet form)
    score: float  # final blended score after rerank
    ragflow_chunk_id: str | None = field(default=None)


@dataclass(slots=True)
class RetrievalResult:
    """Bundles the chunks with the system_prompt block ready to inject."""

    chunks: list[RetrievedChunk]
    # Markdown-ish block the orchestrator drops into system_content.
    # Empty when the bot has no KBs or retrieval failed — caller should
    # still pass an empty block (it's a no-op for the LLM).
    context_block: str


# ─────────────────────────── public API ───────────────────────────


async def retrieve_for_bot(
    bot_id: int,
    query: str,
    session: AsyncSession,
    *,
    top_k: int | None = None,
    top_n: int | None = None,
) -> RetrievalResult:
    """Pull chunks relevant to `query` from every KB mounted on `bot_id`.

    Returns an empty RetrievalResult (no exception) when:
      - the bot has no KBs mounted,
      - the embedding PaaS isn't configured,
      - or nothing matches.

    Network errors are logged and swallowed — the caller treats them
    the same as "no results found".
    """
    if not query.strip():
        return RetrievalResult(chunks=[], context_block="")

    if not local_retriever.is_configured():
        return RetrievalResult(chunks=[], context_block="")

    raw_hits = await local_retriever.retrieve(
        bot_id, query, session, top_k=top_k, top_n=top_n,
    )
    if not raw_hits:
        return RetrievalResult(chunks=[], context_block="")

    # The local retriever already returns hits in (optionally reranked)
    # score-descending order and capped to `top_n`. Convert to
    # RetrievedChunk so the prompt + UI layers stay unchanged.
    enriched: list[RetrievedChunk] = []
    for h in raw_hits:
        filename = (h.get("filename") or h.get("document_name") or "unknown").strip()
        page = h.get("page")
        para = h.get("para")
        snippet_text = (h.get("content") or h.get("snippet") or "").strip()
        if len(snippet_text) > 400:
            snippet_text = snippet_text[:400].rstrip() + "…"
        bbox = h.get("bbox")
        if bbox and not isinstance(bbox, list):
            bbox = list(bbox)
        citation_key = f"{filename} p.{page or '?'} ¶{para or '?'}"
        enriched.append(
            RetrievedChunk(
                citation_key=citation_key,
                chunk_id=int(h.get("chunk_id") or 0),
                kb_id=str(h.get("kb_id") or ""),
                kb_doc_id=int(h.get("kb_doc_id") or 0),
                document_name=filename,
                page=page,
                para=para,
                bbox=bbox,
                snippet=snippet_text,
                score=float(h.get("score") or 0.0),
                ragflow_chunk_id=h.get("ragflow_chunk_id"),
            )
        )

    context_block = _format_context_block(enriched)
    return RetrievalResult(chunks=enriched, context_block=context_block)


# ─────────────────────────── helpers ───────────────────────────


def _format_context_block(chunks: list[RetrievedChunk]) -> str:
    """Render the chunks as a system-prompt block.

    Format mirrors the citation markers the chat LLM is told to emit:

        【知识库参考】（请使用 [doc: ...] 标注每条引用）
        [doc: file.pdf p.3 ¶2] snippet text…
        [doc: file.pdf p.7 ¶1] snippet text…

    The prefix line tells the LLM (a) where the knowledge comes from,
    and (b) how to cite it inline. Mirrors the prompt constraint added
    in `msghub._generate_agent`.
    """
    if not chunks:
        return ""
    lines = [
        "【知识库参考】（请在回答中使用 [doc: filename p.X ¶Y] 标注每条引用；"
        "若参考资料与问题无关，回答“暂未找到相关资料”）",
    ]
    for c in chunks:
        snippet = c.snippet.replace("\n", " ").strip()
        lines.append(f"[doc: {c.citation_key}] {snippet}")
    return "\n".join(lines)
