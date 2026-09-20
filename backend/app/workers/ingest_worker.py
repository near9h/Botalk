"""Background worker that turns an uploaded attachment into KB chunks.

The KB ingest lifecycle:

  1. User uploads a PDF/Word/Excel to `POST /api/kb/{id}/documents`.
     The handler writes an `Attachment` row (status="pending", group
     id NULL because KB docs are not chat attachments), creates a
     `KbDocument` row in `pending` status, then enqueues a job here.

  2. The worker:
       a. Calls MinerU's `parse_pdf_with_chunks` (or word/excel
          equivalent — Word & Excel fall through to plain text for
          now) to get (markdown, list[MinedChunk]).
       b. Lazily creates the RAGFlow dataset the first time a KB is
          ingested, caches its `dataset_id` on the KB row, and
          uploads the document bytes to RAGFlow.
       c. Writes per-chunk rows into `kb_chunks` with bbox metadata
          so the chat UI can highlight the original PDF on citation.
       d. Updates `KbDocument.status` to `ready` / `failed`.

This module is intentionally a *pull* worker (the API enqueues the
job via `asyncio.create_task`, we await the future in the same loop).
For production scale we'd swap that for an external queue (Redis /
RabbitMQ) — the call sites only know about `enqueue()` and don't care
how it's backed.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Attachment, KbChunk, KbDocument, KnowledgeBase
from app.db.session import SessionLocal
from app.services import local_retriever, ragflow_client
from app.services.mineru import MinedChunk, parse_pdf_with_chunks

logger = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────── queue ───────────────────────────


_tasks: set[asyncio.Task] = set()


def enqueue(kb_doc_id: int) -> asyncio.Task:
    """Schedule one KB document for ingestion.

    Returns the asyncio Task so tests can await it. Production callers
    ignore the return value.
    """
    task = asyncio.create_task(_run_safe(kb_doc_id), name=f"kb-ingest-{kb_doc_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def wait_all() -> None:
    """Block until every pending ingest finishes. Used by tests + the
    FastAPI shutdown handler so we don't drop in-flight uploads."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def _run_safe(kb_doc_id: int) -> None:
    """Top-level wrapper: catch every exception so the asyncio task
    doesn't bubble into the event loop's unhandled-exception handler."""
    try:
        await _run(kb_doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("KB ingest crashed for doc_id=%s", kb_doc_id)
        # _run should have flipped the status to `failed` before
        # raising, but if it didn't (e.g. DB error during status
        # update), we still want a clear record.
        await _mark_failed(kb_doc_id, f"unexpected: {exc}"[:2000])


# ─────────────────────────── pipeline ───────────────────────────


async def _run(kb_doc_id: int) -> None:
    async with SessionLocal() as session:
        kb_doc = await session.get(KbDocument, kb_doc_id)
        if not kb_doc:
            logger.error("kb_doc %s disappeared before ingest", kb_doc_id)
            return
        kb = await session.get(KnowledgeBase, kb_doc.kb_id)
        if not kb:
            logger.error("kb %s disappeared before ingest", kb_doc.kb_id)
            return
        att_id = kb_doc.attachment_id

    # We update status outside any DB transaction so the API handler's
    # commit is the source of truth on the happy path.
    await _set_status(kb_doc_id, "parsing", error="")

    try:
        # 1. Load the bytes from the Attachment row (uploads land on disk;
        # see api/kb.py).
        async with SessionLocal() as session:
            att = await session.get(Attachment, att_id)
            if not att or not att.storage_path:
                raise RuntimeError("attachment row missing storage_path")
            file_bytes = Path(att.storage_path).read_bytes()
            kb = await session.get(KnowledgeBase, kb_doc.kb_id)
            if not kb:
                raise RuntimeError("kb row missing")

        # 2. Parse with MinerU. Only PDFs produce bbox-bearing chunks;
        # other formats fall back to a single synthetic chunk.
        mime = (att.mime_type or "").lower()
        chunks: list[MinedChunk] = []
        md = ""
        if mime == "application/pdf" or att.filename.lower().endswith(".pdf"):
            md, chunks = await parse_pdf_with_chunks(att.filename, file_bytes)
        else:
            # Word/Excel/FAQ: hand the raw bytes to RAGFlow and skip the
            # bbox path. RAGFlow's DeepDoc parser does a reasonable
            # job on these without our pre-chunking.
            md = await _read_text(file_bytes, mime)
            chunks = [
                MinedChunk(block_id=0, page=1, text=md[:8000], bbox=[])
            ] if md else []

        # 3. Local-vector path: persist chunks first (so we know the row
        #    ids), then embed them with GLM. If GLM isn't configured we
        #    still keep the chunks (UI shows them as a static preview);
        #    retrieval will return empty because `local_retriever.is_configured()`
        #    is False.
        await _store_chunks(kb_doc_id, chunks)
        if not local_retriever.is_configured():
            logger.info(
                "GLM embedding not configured; chunks persisted without vectors for doc %s",
                kb_doc_id,
            )
        else:
            async with SessionLocal() as embed_session:
                n = await local_retriever.embed_chunks_for_doc(
                    embed_session, kb_doc_id, chunks,
                )
                logger.info(
                    "embedded %s chunks for doc %s (model=%s)",
                    n, kb_doc_id, settings.zhipuai_embedding_model,
                )

        # 4. Best-effort RAGFlow sync kept for backwards compatibility
        #    with existing rows that already have a ragflow_dataset_id.
        #    New KBs skip this path because `is_configured()` returns
        #    False — the orchestrator now reads `kb_chunks.embedding`
        #    instead of hitting RAGFlow.
        if (
            ragflow_client.is_configured()
            and kb.ragflow_dataset_id
        ):
            try:
                await _upload_to_ragflow(kb.id, att, file_bytes, md)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "RAGFlow upload skipped for doc %s: %s", kb_doc_id, exc,
                )

        # 5. Update the doc's bookkeeping.
        async with SessionLocal() as session:
            kb_doc = await session.get(KbDocument, kb_doc_id)
            if kb_doc:
                kb_doc.status = "ready"
                kb_doc.error = ""
                kb_doc.chunk_count = len(chunks)
                await session.commit()
        logger.info(
            "KB ingest done: doc_id=%s chunks=%s",
            kb_doc_id,
            len(chunks),
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("KB ingest failed for doc %s", kb_doc_id)
        await _mark_failed(kb_doc_id, str(exc)[:2000])
        raise


# ─────────────────────────── helpers ───────────────────────────


async def _read_text(file_bytes: bytes, mime: str) -> str:
    """Best-effort text extraction for non-PDF KB uploads.

    Word / Excel binaries are opaque without specialized parsers; we
    hand them to RAGFlow which has DeepDoc for the heavy lifting. For
    our local preview we just decode UTF-8 — anything that's neither
    UTF-8 text nor a PDF goes to RAGFlow only and `kb_chunks` ends up
    with a single "see RAGFlow" placeholder.
    """
    try:
        return file_bytes.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


async def _ensure_ragflow_dataset(
    session: AsyncSession | None,
    kb_id: int,
    kb_name: str,
) -> str:
    """Idempotently create the RAGFlow dataset for a KB.

    Caches the engine-side `dataset_id` on `knowledge_bases.ragflow_dataset_id`
    so we only call create_dataset once per KB.
    """
    async with SessionLocal() as session:
        kb = await session.get(KnowledgeBase, kb_id)
        if not kb:
            raise RuntimeError(f"kb {kb_id} disappeared")
        if kb.ragflow_dataset_id:
            return kb.ragflow_dataset_id

        client = await ragflow_client.get_client()
        dataset_id = await client.create_dataset(
            kb.name, description=kb.description or "",
        )
        kb.ragflow_dataset_id = dataset_id
        await session.commit()
        return dataset_id


async def _upload_to_ragflow(
    kb_id: int,
    att: Attachment,
    file_bytes: bytes,
    md: str,
) -> None:
    """Push the document into RAGFlow.

    The KB row's ragflow_dataset_id is the target. We stash RAGFlow's
    returned doc id on `kb_documents.ragflow_doc_id` so the chat layer
    can deep-link to it later.
    """
    async with SessionLocal() as session:
        kb_doc = await session.get(
            KbDocument,
            select(KbDocument.id).where(KbDocument.attachment_id == att.id).scalar_subquery(),
        )
        # Re-query with select() to be portable across asyncpg + aiosqlite.
        result = await session.execute(
            select(KbDocument).where(KbDocument.attachment_id == att.id)
        )
        kb_doc = result.scalar_one_or_none()
        if not kb_doc:
            raise RuntimeError("kb_doc vanished before upload")

        kb = await session.get(KnowledgeBase, kb_id)
        if not kb or not kb.ragflow_dataset_id:
            raise RuntimeError("ragflow dataset id missing on kb")

        client = await ragflow_client.get_client()
        doc_id = await client.upload_document(
            kb.ragflow_dataset_id,
            filename=att.filename,
            content=file_bytes,
            mime_type=att.mime_type or "application/octet-stream",
        )
        kb_doc.ragflow_doc_id = doc_id
        await session.commit()


async def _store_chunks(kb_doc_id: int, chunks: list[MinedChunk]) -> None:
    """Replace the chunk list for a KB doc.

    We drop existing rows first because the file might be re-uploaded
    (idempotent re-ingest). The FK cascade from `kb_documents` already
    handles hard deletes, so we only need a plain DELETE here.

    The chunk's full `text` body is persisted alongside the 200-char
    `snippet`. With the local-vector retrieval path the full body is
    needed to feed the LLM context after a hit, and embedding-side
    we want the whole text (capped at 4000 chars by the model card).
    """
    async with SessionLocal() as session:
        existing = await session.execute(
            select(KbChunk).where(KbChunk.kb_doc_id == kb_doc_id)
        )
        for row in existing.scalars().all():
            await session.delete(row)
        # 用 Core insert 而不是 `session.add(KbChunk(...))`：`KbChunk.embedding`
        # 在 ORM 里映射成 `Text`，实际列却是 pgvector 的 `vector(2048)`，而 ORM
        # 会把所有「未赋值且可空」的列也写进 INSERT（值为 NULL），于是 asyncpg
        # 生成 `NULL::VARCHAR`，Postgres 直接报
        # `DatatypeMismatchError: column "embedding" is of type vector but
        # expression is of type character varying`。
        # Core insert 只发送显式列出的字段，embedding 完全不进语句；向量随后由
        # `local_retriever.embed_chunks_for_doc` 用带 `::vector` 的裸 SQL 回填。
        rows: list[dict[str, Any]] = []
        for c in chunks:
            text = (c.text or "").strip()[:4000]
            rows.append(
                {
                    "kb_doc_id": kb_doc_id,
                    "ragflow_chunk_id": None,  # local path doesn't use this
                    "page": c.page,
                    "para": c.block_id,
                    "bbox_json": c.bbox or None,
                    "text": text,
                    "snippet": text[:200],
                }
            )
        if rows:
            await session.execute(insert(KbChunk), rows)
        await session.commit()


async def _set_status(kb_doc_id: int, status: str, *, error: str = "") -> None:
    async with SessionLocal() as session:
        kb_doc = await session.get(KbDocument, kb_doc_id)
        if not kb_doc:
            return
        kb_doc.status = status
        kb_doc.error = error
        await session.commit()


async def _mark_failed(kb_doc_id: int, error: str) -> None:
    try:
        await _set_status(kb_doc_id, "failed", error=error)
    except Exception:  # noqa: BLE001
        # Last-resort logging. We never want the worker's failure
        # handler itself to crash the event loop.
        logger.exception("failed to mark doc %s as failed", kb_doc_id)