"""Sentence-Window: pull neighbour chunks around a hit for context.

Why this exists
---------------
MinerU splits a PDF into paragraph-level blocks. A single chunk often
contains the *answer* but not the *context that makes the answer
safe to repeat*. Example from the SG corpus: the chunk
``"Referral to SPC / Treaty is required"`` is technically correct, but
the LLM, given only that line, will write a generic "referral is
mandatory" answer; given the surrounding paragraph it knows SPC and
Treaty are *named recipients* and will quote them in the prose.

Pattern (sentence-window retrieval): match small, return big. See
LangChain's ``ParentDocumentRetriever`` and the ai-tldr.dev "What is
parent document retrieval" article for the formal treatment; this
module implements the sentence-window variant on top of the existing
``kb_chunks`` schema.

Index side: unchanged. MinerU already gives us per-block chunks with
``page`` + ``para`` (MinerU's per-page block index) continuity. We
reuse ``para`` as the block sequence number — no schema migration.

Retrieval side: when ``settings.rag_window_size > 0``, ``retrieve()``
replaces each hit's ``content`` with the stitched text of its
``para-window`` … ``para+window`` siblings (sparse ``para`` values
are fine — we use ``BETWEEN`` inclusive).
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def fetch_window(
    session: AsyncSession,
    *,
    kb_doc_id: int,
    page: int | None,
    para: int | None,
    window: int,
) -> list[dict]:
    """Return all ``kb_chunks`` with ``para`` in
    ``[para-window, para+window]`` for the same ``kb_doc_id + page``.

    Empty list when ``window <= 0`` or ``page``/``para`` are missing.
    Sparse ``para`` values (MinerU sometimes skips whitespace blocks)
    are handled gracefully — we just take whatever falls in the
    inclusive range and let the caller sort by ``para``.

    The query plan should hit the existing
    ``ix_kb_chunks_kb_doc_id`` btree on ``(kb_doc_id)`` plus a small
    in-memory sort over a handful of rows; for ~3-row windows the
    cost is negligible.
    """
    if window <= 0 or page is None or para is None:
        return []
    rows = (
        await session.execute(
            text(
                """
                SELECT id, kb_doc_id, page, para, text, snippet,
                       bbox_json, ragflow_chunk_id, embedding_model
                FROM kb_chunks
                WHERE kb_doc_id = :doc_id
                  AND page = :page
                  AND para BETWEEN :lo AND :hi
                ORDER BY para ASC
                """
            ),
            {
                "doc_id": kb_doc_id,
                "page": page,
                "lo": para - window,
                "hi": para + window,
            },
        )
    ).mappings().all()
    out = [dict(r) for r in rows]
    logger.debug(
        "sentence_window: kb_doc_id=%s page=%s para=%s window=%s → %s siblings",
        kb_doc_id, page, para, window, len(out),
    )
    return out


def stitch_text(siblings: Iterable[dict]) -> str:
    """Concatenate sibling chunks with ``\\n\\n`` boundaries.

    Empty / None ``text`` fields are skipped — MinerU occasionally
    emits an empty block that we still keep around (so block_seq
    numbers stay stable across re-ingest).
    """
    parts = [s["text"].strip() for s in siblings if s.get("text")]
    return "\n\n".join(parts)