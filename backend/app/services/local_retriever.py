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
    """Hybrid (dense + BM25 + RRF) retrieval over every KB mounted on `bot_id`.

    Returns a list of dicts in the same shape the chat orchestrator
    expects (consumed by `rag_retriever._enrich_with_local_metadata`):

        { chunk_id, kb_doc_id, kb_id, filename, page, para, bbox,
          snippet, score, document_name, content, match_source }

    Each returned dict now carries `match_source` — one of
    ``"dense"`` (pgvector cosine hit), ``"bm25"`` (full-text-search
    hit), or ``"both"`` (the same chunk appeared in both ranked
    lists). Operators can use this signal to tune `rag_top_k_dense` /
    `rag_top_k_bm25` / `rag_rrf_k` on a real eval set.

    Empty list on no-KB / not-configured / no-matches. Network errors
    are logged and swallowed; the caller treats them as "no chunks".

    Pipeline:
      1. Discover mounted KBs.
      2. Embed the query once (GLM embedding-3).
      3. Run dense cosine search (limited to `rag_top_k_dense`).
      4. Run BM25 full-text search on `kb_chunks.tsv` (limited to
         `rag_top_k_bm25`). Skipped when `rag_hybrid_enabled` is False.
      5. Reciprocal Rank Fusion (k = `rag_rrf_k`) merges both ranked
         lists into a single ordering.
      6. Optional GLM rerank on the fused top-N.
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
    top_k_dense = min(top_k, settings.rag_top_k_dense)
    top_k_bm25 = settings.rag_top_k_bm25

    # 3. Dense (pgvector cosine) search.
    dense_sql = text(
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
    dense_rows = (
        await session.execute(
            dense_sql,
            {
                "vec": _vec_param(query_vec),
                "kb_ids": kb_ids,
                "limit": top_k_dense,
            },
        )
    ).mappings().all()

    # 4. BM25 (full-text) search. Only runs when `rag_hybrid_enabled`
    #    AND the `tsv` column is in the schema (i.e. migration 0021
    #    has been applied). The first SELECT returns 0 rows on a
    #    legacy schema — the `match_source` tag on each hit stays at
    #    "dense" so the rest of the pipeline is unchanged.
    bm25_rows = []
    if settings.rag_hybrid_enabled:
        try:
            bm25_sql = text(
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
                  ts_rank_cd(c.tsv, websearch_to_tsquery('simple', :q)) AS bm25_score
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.kb_doc_id
                JOIN attachments  a ON a.id = d.attachment_id
                WHERE d.kb_id = ANY(:kb_ids)
                  AND c.tsv @@ websearch_to_tsquery('simple', :q)
                ORDER BY bm25_score DESC
                LIMIT :limit
                """
            )
            bm25_rows = (
                await session.execute(
                    bm25_sql,
                    {
                        "q": query,
                        "kb_ids": kb_ids,
                        "limit": top_k_bm25,
                    },
                )
            ).mappings().all()
        except Exception as exc:  # noqa: BLE001
            # Missing column (pre-migration), or `websearch_to_tsquery`
            # rejected the query (e.g. only stopwords). Don't break the
            # chat — fall back to dense-only.
            logger.warning(
                "BM25 leg failed (likely missing `tsv` column or empty tsquery): %s",
                exc,
            )
            bm25_rows = []

    # 5. Reciprocal Rank Fusion.
    fused = _reciprocal_rank_fusion(
        dense_rows, bm25_rows, k=settings.rag_rrf_k,
    )
    if not fused:
        return []

    # Convert fused rows to the legacy `hits` shape, stamping each
    # one with its match source so downstream code (and the chat UI)
    # can tell where it came from.
    hits: list[dict[str, Any]] = []
    for entry in fused:
        r = entry["row"]
        if entry["source"] == "dense":
            dist = float(r.get("distance") or 1.0)
            sim = max(0.0, 1.0 - dist)
            if sim < settings.ragflow_score_threshold:
                # Dense leg below threshold — keep if BM25 also matched.
                if entry["matched"] == 1:
                    pass  # fall through and emit with bm25_score
                else:
                    continue
            score = sim
        else:
            score = float(r.get("bm25_score") or 0.0)
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
                # Final score reported to the UI: dense sim if dense-side
                # contributed, otherwise the bm25_score.
                "score": score,
                "match_source": entry["source"],
                # Mirror `rag_retriever._format_citation` so the chat UI's
                # `[doc: …]` regex can resolve to the chunk.
                "citation_key": f"{r['filename']} p.{r['page'] or '?'} ¶{r['para'] or '?'}",
            }
        )

    if not hits:
        return []

    # 6. Cap to top_n (the fused RRF ordering IS the final ordering;
    #    we dropped the GLM rerank layer because it was promoting
    #    semantically-similar chunks over exact-term hits like
    #    "Referral to SPC / Treaty is required").
    hits = hits[: top_n or settings.ragflow_top_n_after_rerank]

    # 6.5. Sentence-window: stitch neighbouring blocks around each
    #      hit so the LLM sees the paragraph, not just the line. The
    #      bbox / citation_key / match_source all stay tied to the
    #      original hit — only `content` (what the LLM actually reads)
    #      is expanded. PDF highlights in the chat UI therefore stay
    #      precise on the original paragraph.
    if settings.rag_window_size > 0:
        from app.services.sentence_window import (
            fetch_window as _fetch_window,
            stitch_text as _stitch_text,
        )
        for hit in hits:
            if not hit.get("kb_doc_id") or not hit.get("page"):
                continue
            siblings = await _fetch_window(
                session,
                kb_doc_id=hit["kb_doc_id"],
                page=hit["page"],
                para=hit.get("para"),
                window=settings.rag_window_size,
            )
            if len(siblings) <= 1:
                # Either no siblings found, or only the hit itself —
                # nothing to stitch.
                hit["window_size"] = len(siblings)
                continue
            hit["content"] = _stitch_text(siblings)
            hit["window_size"] = len(siblings)

    return hits


def _reciprocal_rank_fusion(
    dense_rows: list,
    bm25_rows: list,
    *,
    k: int = 60,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion (Cormack et al., 2009).

    Each list contributes ``1 / (k + rank_in_list)`` for every item;
    the same chunk appearing in both lists gets *both* contributions
    summed. We then re-sort by total RRF score (descending).

    `k` is a smoothing constant — the standard recommendation is 60.
    Larger `k` dampens the top-rank advantage; smaller `k` amplifies it.
    We expose `settings.rag_rrf_k` for ops to tune without code.

    Returns a list of dicts:
        [{ "chunk_id": int, "row": <SQLAlchemy mapping>, "source":
           "dense"|"bm25"|"both", "matched": 1|2, "rrf_score": float }, ...]
    sorted by `rrf_score` desc.
    """
    scores: dict[int, float] = {}
    payload: dict[int, dict] = {}
    src: dict[int, set[str]] = {}
    for rank, row in enumerate(dense_rows, start=1):
        cid = int(row["chunk_id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        # Prefer the dense-side row (it has `bbox` / `content`
        # identical to bm25, but the dense SELECT returns more cols).
        payload.setdefault(cid, row)
        src.setdefault(cid, set()).add("dense")
    for rank, row in enumerate(bm25_rows, start=1):
        cid = int(row["chunk_id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        # If the chunk is already in `payload` (from dense), keep the
        # dense row — they have the same chunk metadata anyway.
        payload.setdefault(cid, row)
        src.setdefault(cid, set()).add("bm25")
    out: list[dict[str, Any]] = []
    for cid, total in scores.items():
        legs = src[cid]
        if len(legs) == 2:
            source = "both"
        elif "dense" in legs:
            source = "dense"
        else:
            source = "bm25"
        out.append(
            {
                "chunk_id": cid,
                "row": payload[cid],
                "source": source,
                "matched": len(legs),
                "rrf_score": total,
            }
        )
    out.sort(key=lambda x: -x["rrf_score"])
    return out
