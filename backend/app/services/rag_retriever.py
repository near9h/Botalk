"""Bot-aware RAG retrieval: pulls chunks from mounted knowledge bases,
optionally re-ranks them with GLM, and returns the slice of metadata
the chat orchestrator needs to inject into the LLM prompt.

Pipeline:

    retrieve_for_bot(bot_id, query)
      │
      ├─ look up bot_kb → KB ids the bot has mounted
      ├─ for each KB:
      │     ├─ skip if not configured or empty ragflow_dataset_id
      │     └─ RAGFlow.retrieval(dataset_id, query, top_k=cfg.top_k)
      ├─ merge results from all KBs, score-sort
      ├─ (optional) GLM rerank(query, snippets) → top_n_after_rerank
      └─ resolve ragflow_chunk_id → kb_chunks row for page / bbox
         so the chat UI can light up the PDF.js overlay.

Why a separate module rather than inlining in `msghub.py`:
  - It owns its own DB session lifecycle and isolates network failures
    (RAGFlow down, GLM quota exhausted) so the chat path can degrade
    gracefully and still emit a normal answer.
  - The chunk metadata mapping (ragflow_chunk_id → bbox) is dense and
    benefits from its own dataclass + helpers.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    Attachment,
    BotKb,
    KbChunk,
    KbDocument,
    KnowledgeBase,
)
from app.services import ragflow_client, zhipuai_embed

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
    # `GET /api/kb/{kb_id}/chunks/{chunk_id}` for the bbox payload.
    chunk_id: int
    kb_id: int
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
      - RAG is disabled / RAGFlow isn't deployed,
      - or every mounted KB has no `ragflow_dataset_id` yet (first
        ingest hasn't happened).

    Network errors from RAGFlow or GLM are logged and swallowed — the
    caller treats them the same as "no results found".
    """
    if not query.strip():
        return RetrievalResult(chunks=[], context_block="")

    # Short-circuit when RAG is fully disabled in config — avoids paying
    # for the DB round-trip + the bot_kb query when no chunks can ever
    # be returned. RAGFlow-not-configured is handled later (per-KB skip).
    if not ragflow_client.is_configured():
        return RetrievalResult(chunks=[], context_block="")

    # 1. Discover mounted KBs. Single round-trip; we don't filter on
    #    scope here because the bot mount itself already went through
    #    the visibility gate in `_resolve_visible_kb`.
    kb_rows = (
        await session.execute(
            select(KnowledgeBase, BotKb.weight)
            .join(BotKb, BotKb.kb_id == KnowledgeBase.id)
            .where(BotKb.bot_id == bot_id)
        )
    ).all()
    if not kb_rows:
        return RetrievalResult(chunks=[], context_block="")

    top_k = top_k or settings.ragflow_top_k
    top_n = top_n or settings.ragflow_top_n_after_rerank

    # 2. Fan out to RAGFlow per KB. `gather(..., return_exceptions=True)`
    #    so a single dataset failure doesn't kill the whole answer.
    client = await ragflow_client.get_client()
    per_kb_calls: list[asyncio.Task] = []
    for kb, _weight in kb_rows:
        if not kb.ragflow_dataset_id:
            logger.info(
                "kb %s has no ragflow_dataset_id yet; skipping retrieval",
                kb.id,
            )
            continue
        per_kb_calls.append(
            asyncio.create_task(
                _safe_retrieval(client, kb.ragflow_dataset_id, query, top_k)
            )
        )

    raw_hits: list[dict[str, Any]] = []
    if per_kb_calls:
        results = await asyncio.gather(*per_kb_calls, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("ragflow retrieval failed: %s", r)
                continue
            if isinstance(r, list):
                raw_hits.extend(r)

    if not raw_hits:
        return RetrievalResult(chunks=[], context_block="")

    # 3. Sort by RAGFlow score desc, then take a generous slice for
    #    rerank. Rerank is the expensive step; we cap its input here.
    raw_hits.sort(key=lambda h: float(h.get("score") or 0.0), reverse=True)
    rerank_input = raw_hits[: max(top_n * 3, top_n)]

    # 4. Optional rerank. If GLM fails (quota / network) we fall back
    #    to the RAGFlow ordering rather than dropping the chunks.
    if settings.zhipuai_rerank_enabled and zhipuai_embed.is_configured():
        try:
            docs = [h.get("content") or h.get("text") or "" for h in rerank_input]
            ranked = await zhipuai_embed.rerank(query, docs, top_n=top_n)
            # ranked entries are {index, score, document}; map back to
            # the original hit so we keep its positions / document_name.
            reranked_hits: list[dict[str, Any]] = []
            for entry in ranked:
                idx = int(entry["index"])
                if 0 <= idx < len(rerank_input):
                    hit = dict(rerank_input[idx])
                    hit["score"] = float(entry["score"])
                    reranked_hits.append(hit)
            hits = reranked_hits
        except Exception as exc:  # noqa: BLE001
            logger.warning("GLM rerank failed (%s); using RAGFlow ranking", exc)
            hits = rerank_input[:top_n]
    else:
        hits = rerank_input[:top_n]

    # 5. Enrich each hit with our local metadata (page / bbox) so the
    #    chat UI can render citations. We join through ragflow_chunk_id
    #    when RAGFlow returned one; otherwise we fall back to a
    #    snippet-only stub (still useful for the LLM context).
    enriched = await _enrich_with_local_metadata(hits, session)

    # 6. Build the prompt-side context block. The LLM is told to cite
    #    each reference inline via `[doc: key]` — we keep the keys short
    #    so they fit on one line of model output.
    context_block = _format_context_block(enriched)

    return RetrievalResult(chunks=enriched, context_block=context_block)


# ─────────────────────────── helpers ───────────────────────────


async def _safe_retrieval(
    client: ragflow_client.RAGFlowClient,
    dataset_id: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Wrap the RAGFlow call so a single failure becomes an empty list."""
    try:
        return await client.retrieval(dataset_id, query, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "RAGFlow retrieval on dataset %s failed: %s",
            dataset_id,
            exc,
        )
        return []


async def _enrich_with_local_metadata(
    hits: list[dict[str, Any]],
    session: AsyncSession,
) -> list[RetrievedChunk]:
    """Map RAGFlow hits → RetrievedChunk.

    RAGFlow's chunk id (when present) is what `kb_chunks.ragflow_chunk_id`
    stores. We issue one query that joins chunks ↔ documents ↔
    attachments so we get page / bbox / filename in a single round trip.
    Hits whose chunk id isn't found in our local cache (e.g. RAGFlow
    returned a fresh chunk we haven't mirrored yet) still surface — we
    just synthesize a chunk_id of 0 and use the raw snippet.
    """
    chunk_ids = [str(h.get("id") or h.get("chunk_id") or "") for h in hits]
    chunk_ids = [c for c in chunk_ids if c]
    metadata_by_rid: dict[str, dict[str, Any]] = {}
    if chunk_ids:
        rows = (
            await session.execute(
                select(
                    KbChunk.id,
                    KbChunk.ragflow_chunk_id,
                    KbChunk.kb_doc_id,
                    KbChunk.page,
                    KbChunk.para,
                    KbChunk.bbox_json,
                    KbChunk.snippet,
                    KbDocument.kb_id,
                    Attachment.filename,
                )
                .join(KbDocument, KbDocument.id == KbChunk.kb_doc_id)
                .join(Attachment, Attachment.id == KbDocument.attachment_id)
                .where(KbChunk.ragflow_chunk_id.in_(chunk_ids))
            )
        ).all()
        for row in rows:
            metadata_by_rid[row.ragflow_chunk_id] = {
                "chunk_id": row.id,
                "kb_doc_id": row.kb_doc_id,
                "kb_id": row.kb_id,
                "page": row.page,
                "para": row.para,
                "bbox": list(row.bbox_json) if row.bbox_json else None,
                "snippet": row.snippet or "",
                "filename": row.filename,
            }

    enriched: list[RetrievedChunk] = []
    for idx, hit in enumerate(hits, start=1):
        rid = str(hit.get("id") or hit.get("chunk_id") or "")
        meta = metadata_by_rid.get(rid)
        snippet_text = (hit.get("content") or hit.get("text") or "").strip()
        # Cap to ~400 chars per chunk in the prompt — long enough to
        # convey meaning, short enough not to blow context budget.
        if len(snippet_text) > 400:
            snippet_text = snippet_text[:400].rstrip() + "…"

        if meta:
            filename = meta["filename"] or "unknown"
            page = meta["page"]
            para = meta["para"]
            citation_key = f"{filename} p.{page or '?'} ¶{para or '?'}"
            enriched.append(
                RetrievedChunk(
                    citation_key=citation_key,
                    chunk_id=meta["chunk_id"],
                    kb_id=meta["kb_id"],
                    kb_doc_id=meta["kb_doc_id"],
                    document_name=filename,
                    page=page,
                    para=para,
                    bbox=meta["bbox"],
                    snippet=snippet_text or meta["snippet"],
                    score=float(hit.get("score") or 0.0),
                    ragflow_chunk_id=rid,
                )
            )
        else:
            # Fallback: no local metadata (chunk not yet mirrored or
            # source is a non-PDF RAGFlow parse). Still useful context —
            # the LLM gets a generic citation key.
            fallback_name = (hit.get("document_name") or "unknown").strip()
            citation_key = f"{fallback_name} (RAGFlow)"
            enriched.append(
                RetrievedChunk(
                    citation_key=citation_key,
                    chunk_id=0,
                    kb_id=0,
                    kb_doc_id=0,
                    document_name=fallback_name,
                    page=None,
                    para=None,
                    bbox=None,
                    snippet=snippet_text,
                    score=float(hit.get("score") or 0.0),
                    ragflow_chunk_id=rid,
                )
            )
    return enriched


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
