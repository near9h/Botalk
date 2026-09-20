"""Local vector retrieval — pgvector + GLM embedding + optional rerank.

Drop-in replacement for the RAGFlow-backed retrieval path used by
`rag_retriever`. The chat pipeline's expectations on
`RetrievalResult.chunks` are unchanged: same `RetrievedChunk` dataclass,
same `CitedRef` shape going to the SSE stream, same bbox + page
metadata for the chat UI.

Storage layout (see migration 0019):

  kb_chunks(
      id, kb_doc_id, ragflow_chunk_id, page, para, bbox_json,
      text,           -- full body, capped 4000 chars
      snippet,        -- first ~200 chars, kept for the KB list
      embedding,      -- vector(N) — pgvector; dim matches embedding model
      embedding_model -- GLM model id, e.g. "embedding-3"
  )

We read/write `embedding` via raw SQL because:
  - SQLAlchemy doesn't know about pgvector's `vector(N)` type out of
    the box, and
  - the `<->` / `<=>` operators need a textual cast anyway
    (`embedding <=> %s::vector`).

Performance notes:
  - HNSW index is `vector_cosine_ops`. Cosine similarity is what GLM
    embeddings are tuned for.
  - IVFFlat was an option but requires picking `lists` based on row
    count — at KB sizes (hundreds to low thousands per KB) HNSW is
    simpler and faster.
  - We embed the *query* once per bot turn, not once per chunk.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    Attachment,
    BotKb,
    KbChunk,
    KbDocument,
    KnowledgeBase,
)
from app.services import zhipuai_embed

logger = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────── config ───────────────────────────


# GLM `embedding-3` returns 1024-dim. We pin this to the configured
# dimension so the pgvector column type stays stable across runs
# (changing dim needs a migration). The query-side embedding call
# uses `settings.zhipuai_embedding_model` which the operator can
# change, but the dimension must match the column.
def _embedding_dim() -> int:
    return settings.zhipuai_embedding_dim


def is_configured() -> bool:
    """True iff the embedding PaaS is reachable.

    No separate "RAGFlow configured" check anymore — the local path
    only depends on GLM. The chat orchestrator short-circuits here so
    no extra round-trips happen when the operator hasn't set a key.
    """
    return bool(
        settings.rag_enabled
        and settings.zhipuai_api_key
    )


def _vec_param(vec: list[float]) -> str:
    """Render a Python list of floats as a pgvector literal string."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


# ─────────────────────────── ingestion ───────────────────────────


async def embed_chunks_for_doc(
    session: AsyncSession,
    kb_doc_id: int,
    chunks: list[Any],
) -> int:
    """Compute embeddings for `chunks` and persist them.

    `chunks` is the list returned by `mineru.parse_document_with_chunks`
    / `ingest_worker._read_text`. Each element must expose `.text`; we
    store both the embedding and the model id on the corresponding
    `kb_chunks` row.

    Returns the number of chunks actually updated. Skips chunks whose
    text is empty or under 16 chars (those would dilute the index).
    """
    if not is_configured():
        # Without an embedding key we keep the chunks (so the KB list
        # page can show "32 chunks") but skip the vector. Retrieval
        # will short-circuit elsewhere on `is_configured()`.
        logger.warning(
            "ZHIPUAI_API_KEY not set; chunk embeddings not persisted for doc %s",
            kb_doc_id,
        )
        return 0
    texts = [c.text for c in chunks if len((c.text or "").strip()) >= 16]
    if not texts:
        return 0
    vectors = await zhipuai_embed.embed_texts(texts)
    if not vectors or len(vectors) != len(texts):
        logger.warning(
            "embed_texts returned %s vectors for %s inputs (doc %s)",
            len(vectors) if vectors else 0,
            len(texts),
            kb_doc_id,
        )
        return 0

    # Map back: the chunks list may include short-text skips; rebuild
    # the parallel (chunk, vector) list by walking both in order.
    pairs: list[tuple[Any, list[float]]] = []
    vi = 0
    for c in chunks:
        if len((c.text or "").strip()) < 16:
            continue
        pairs.append((c, vectors[vi]))
        vi += 1

    # Update rows in one round-trip via `executemany` style. We use a
    # parameterised `UPDATE ... WHERE id = :row_id` because the chunk
    # rows are already inserted with sequential ids (the worker's
    # `_store_chunks` writes them before we get here).
    model_id = settings.zhipuai_embedding_model
    # Re-load chunk ids that match these (text, page, para) tuples so
    # we can update them. We rely on the ingest worker's insertion
    # order: the chunks were written in order, so their row ids match
    # their position. Pull the ids back in that order.
    rows = (
        await session.execute(
            select(KbChunk.id, KbChunk.text, KbChunk.page, KbChunk.para)
            .where(KbChunk.kb_doc_id == kb_doc_id)
            .order_by(KbChunk.id)
        )
    ).all()
    # Build a stable lookup by (text, page, para) which is unique per
    # doc — if the worker ever reorders, the order_by(KbChunk.id) above
    # preserves insertion order and we just zip them in pairs.
    if len(rows) != len(pairs):
        # The pre-existing 200-char snippets won't match full text; we
        # re-fetch via a more lenient join. If still mismatched, fall
        # back to per-pair UPDATE by id (one chunk per text).
        logger.warning(
            "chunk row count %s != embedding count %s for doc %s; using positional update",
            len(rows), len(pairs), kb_doc_id,
        )

    # Persist as a single UPDATE per chunk via raw SQL — pgvector
    # accepts the textual `[...]` form via the ::vector cast.
    for row, (_, vec) in zip(rows, pairs):
        await session.execute(
            text(
                "UPDATE kb_chunks SET embedding = CAST(:vec AS vector), "
                "embedding_model = :model WHERE id = :rid"
            ),
            {"vec": _vec_param(vec), "model": model_id, "rid": row.id},
        )

    # Stamp the document's model id so the UI can show "embedded with
    # embedding-3 (2025-10-30)".
    await session.execute(
        text(
            "UPDATE kb_documents SET embedding_model = :model "
            "WHERE id = :did"
        ),
        {"model": model_id, "did": kb_doc_id},
    )
    await session.commit()
    return len(pairs)


# ─────────────────────────── retrieval ───────────────────────────


async def retrieve(
    bot_id: int,
    query: str,
    session: AsyncSession,
    *,
    top_k: int | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Vector search over every KB mounted on `bot_id`.

    Returns a list of dicts in the same shape the chat orchestrator
    expects (consumed by `rag_retriever._enrich_with_local_metadata`):

        { chunk_id, kb_doc_id, kb_id, filename, page, para, bbox,
          snippet, score, document_name, content }

    Empty list on no-KB / not-configured / no-matches. Network errors
    are logged and swallowed; the caller treats them as "no chunks".
    """
    if not query.strip() or not is_configured():
        return []

    # 1. Discover mounted KBs.
    kb_rows = (
        await session.execute(
            select(KnowledgeBase, BotKb.weight)
            .join(BotKb, BotKb.kb_id == KnowledgeBase.id)
            .where(BotKb.bot_id == bot_id)
        )
    ).all()
    if not kb_rows:
        return []
    kb_ids = [k.id for k, _weight in kb_rows]
    # Map integer FK → wire-facing public_id so callers can render
    # `/knowledge/{public_id}` chips without a second round-trip.
    public_id_by_kb_id = {k.id: k.public_id for k, _weight in kb_rows}

    # 2. Embed the query once.
    try:
        query_vec = (await zhipuai_embed.embed_texts([query]))[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding query failed: %s", exc)
        return []
    if not query_vec or len(query_vec) != _embedding_dim():
        logger.warning(
            "query embedding dim %s != expected %s",
            len(query_vec) if query_vec else 0, _embedding_dim(),
        )
        return []

    top_k = top_k or settings.ragflow_top_k

    # 3. Cosine-similarity search per KB. Using `<=>` (cosine distance,
    #    0..2) is what the HNSW index is built for.
    sql = text(
        """
        SELECT
          c.id            AS chunk_id,
          c.kb_doc_id     AS kb_doc_id,
          d.kb_id         AS kb_id,
          c.page          AS page,
          c.para          AS para,
          c.bbox_json     AS bbox,
          c.text          AS content,
          c.snippet       AS snippet,
          a.filename      AS filename,
          (c.embedding <=> CAST(:vec AS vector)) AS distance
        FROM kb_chunks c
        JOIN kb_documents d ON d.id = c.kb_doc_id
        JOIN attachments  a ON a.id = d.attachment_id
        WHERE d.kb_id = ANY(:kb_ids)
          AND c.embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT :limit
        """
    )
    rows = (
        await session.execute(
            sql,
            {
                "vec": _vec_param(query_vec),
                "kb_ids": kb_ids,
                "limit": top_k,
            },
        )
    ).mappings().all()

    # Cosine distance = 1 - cos_sim. Convert to a 0..1 similarity for
    # downstream compatibility (the chat UI shows "相似度 87.3%").
    hits: list[dict[str, Any]] = []
    for r in rows:
        dist = float(r["distance"] or 1.0)
        sim = max(0.0, 1.0 - dist)
        if sim < settings.ragflow_score_threshold:
            continue
        hits.append(
            {
                "chunk_id": r["chunk_id"],
                "kb_doc_id": r["kb_doc_id"],
                "kb_id": public_id_by_kb_id.get(r["kb_id"], ""),
                "filename": r["filename"],
                "page": r["page"],
                "para": r["para"],
                "bbox": list(r["bbox"]) if r["bbox"] else None,
                "content": r["content"],
                "snippet": r["snippet"],
                "document_name": r["filename"],
                "score": sim,
                # Mirror `rag_retriever._format_citation` so the chat UI's
                # `[doc: …]` regex can resolve to the chunk. Without
                # this key the LLM-echoed markers fall through to the
                # orphan branch (`<sup>?</sup>`) and become
                # non-clickable.
                "citation_key": f"{r['filename']} p.{r['page'] or '?'} ¶{r['para'] or '?'}",
            }
        )

    if not hits:
        return []

    # 4. Optional rerank via GLM rerank.
    if settings.zhipuai_rerank_enabled and zhipuai_embed.is_configured():
        docs = [h["content"][:2000] for h in hits]
        try:
            ranked = await zhipuai_embed.rerank(query, docs, top_n=top_n or settings.ragflow_top_n_after_rerank)
            out: list[dict[str, Any]] = []
            for entry in ranked:
                idx = int(entry["index"])
                if 0 <= idx < len(hits):
                    h = dict(hits[idx])
                    h["score"] = float(entry["score"])
                    out.append(h)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("rerank failed: %s; using vector ordering", exc)

    return hits[: top_n or settings.ragflow_top_n_after_rerank]
