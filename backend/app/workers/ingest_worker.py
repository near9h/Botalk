"""Background worker that turns an uploaded attachment into KB chunks.

The KB ingest lifecycle:

  1. User uploads a PDF / Word / PPT / 纯文本 to `POST /api/kb/{id}/documents`.
     The handler writes an `Attachment` row (status="pending", group
     id NULL because KB docs are not chat attachments), creates a
     `KbDocument` row in `pending` status, then enqueues a job here.

  2. The worker:
       a. Parses by format: PDF / Word / PPT go through MinerU
          (`parse_document_with_chunks`); plain-text formats are decoded
          directly. Anything else is rejected with a clear error — see
          `_MINERU_EXTS` / `_TEXT_EXTS`.
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
import re
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Attachment, KbChunk, KbDocument, KnowledgeBase
from app.db.session import SessionLocal
from app.services import local_retriever, ragflow_client
from app.services.mineru import MinedChunk, parse_document_with_chunks

logger = logging.getLogger(__name__)
settings = get_settings()

# 走 MinerU 解析的格式。它内部的 Precision Extract API 支持
# PDF / 图片 / Doc(Docx) / Ppt(Pptx)，Office 文件会被转成 PDF 后返回同一套
# `full.md` + `layout.json`。
_MINERU_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}

# 真正是纯文本、可以直接 UTF-8 解码的格式。
# 注意 .docx/.pptx/.xlsx 是 ZIP 容器，绝不能走这条路：按文本解码得到的是
# 二进制乱码，而且里面带 NUL，Postgres 的 text 列会直接拒收。
# .html/.htm 也不走 MinerU —— HTML 需要 `MinerU-HTML` 模型版本，本服务固定
# 用 vlm/pipeline，所以按文本读即可。
_TEXT_EXTS = {".txt", ".md", ".markdown", ".html", ".htm"}

# Postgres 的 text/varchar 列存不下 NUL；其余 C0 控制符（保留 \t\n\r）
# 一并清掉，避免解析器产出脏字符后再炸一次插入。
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# 没有 layout 信息时（Office 文件、纯文本）按段落聚合的目标长度。
# 实测 38KB 的 docx 能出 5700+ 字符 markdown，整篇塞一个 chunk 会被
# `_store_chunks` 的 4000 字符上限截断，长文档后半部分就静默搜不到了。
_FALLBACK_CHUNK_CHARS = 800


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

        # 2. 按格式分流解析。Office 文件（doc/docx/ppt/pptx）与 PDF 走同一
        #    条 MinerU 通路；纯文本直接解码；其余格式明确报错，不要拿二进制
        #    去猜文本。
        suffix = Path(att.filename or "").suffix.lower()
        mime = (att.mime_type or "").lower()
        chunks: list[MinedChunk] = []
        md = ""
        if suffix in _MINERU_EXTS or mime == "application/pdf":
            md, chunks = await parse_document_with_chunks(att.filename, file_bytes)
            # MinerU 对 Office 文件只回 full.md、不回 layout.json，所以
            # docx/pptx 这里必然拿不到逐块 bbox。直接留着空 chunk 列表的话
            # 文档会显示 ready 却一条都检索不到 —— 静默失败比报错更难查。
            if not chunks and md:
                logger.warning(
                    "MinerU returned no layout chunks for %s; splitting the "
                    "markdown instead (no bbox highlights)",
                    att.filename,
                )
                chunks = _markdown_chunks(md)
        elif suffix in _TEXT_EXTS:
            md = _read_text(file_bytes)
            chunks = _markdown_chunks(md) if md else []
        else:
            raise RuntimeError(
                f"暂不支持解析 {suffix or mime or '未知格式'} 文件："
                "目前支持 PDF / Word / PPT / 纯文本，请转换格式后重新上传"
            )

        # 3. Local-vector path: persist chunks first (so we know the row
        #    ids), then embed them with GLM. If GLM isn't configured we
        #    still keep the chunks (UI shows them as a static preview);
        #    retrieval will return empty because `local_retriever.is_configured()`
        #    is False.
        stored = await _store_chunks(kb_doc_id, chunks)
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
                kb_doc.chunk_count = stored
                await session.commit()
        logger.info(
            "KB ingest done: doc_id=%s chunks=%s",
            kb_doc_id,
            stored,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("KB ingest failed for doc %s", kb_doc_id)
        await _mark_failed(kb_doc_id, str(exc)[:2000])
        raise


# ─────────────────────────── helpers ───────────────────────────


def _read_text(file_bytes: bytes) -> str:
    """读取纯文本 KB 上传（.txt / .md / .html 等）。

    只对真正是文本的格式调用 —— Office 文件是 ZIP 容器，走 `_MINERU_EXTS`
    那条路，绝不能在这里按 UTF-8 解码。

    解码出来如果是二进制（例如把 .docx 改名成 .txt 上传），内容会带 NUL。
    这种情况宁可当作空文档，也不要把乱码塞进 kb_chunks 污染检索。
    """
    text = file_bytes.decode("utf-8", errors="replace")
    if "\x00" in text:
        logger.warning("KB text upload decoded to binary content; skipping")
        return ""
    return text


def _clean_text(s: str) -> str:
    """清掉 Postgres 的 text/varchar 存不下的控制字符。

    `\\x00` 是合法 UTF-8 码点，`decode(errors="replace")` 不会剔除它，但
    Postgres 会报 `invalid byte sequence for encoding "UTF8": 0x00`。入库是
    所有 chunk 文本的唯一收口，在这里兜底，保证任何解析器的输出都不会把
    插入语句炸掉。
    """
    return _CONTROL_CHARS_RE.sub("", s or "")


def _markdown_chunks(md: str) -> list[MinedChunk]:
    """把没有 layout 信息的 markdown 切成可检索的 chunk。

    用于 Office 文件（MinerU 只给 full.md）和纯文本。按空行分段、再聚合到
    `_FALLBACK_CHUNK_CHARS` 左右，避免整篇被 4000 字符上限截断。这些 chunk
    没有 bbox，所以前端不会画高亮，只显示命中片段。

    `block_id` 复用成段序：`_store_chunks` 会把它写进 `kb_chunks.para`，
    于是引用角标能显示出「第几段」。
    """
    pieces: list[str] = []
    buf = ""
    for para in md.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if not buf:
            buf = para
        elif len(buf) + len(para) + 2 > _FALLBACK_CHUNK_CHARS:
            pieces.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}"
    if buf:
        pieces.append(buf)
    return [
        MinedChunk(block_id=i, page=1, text=p, bbox=[])
        for i, p in enumerate(pieces)
    ]


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


async def _store_chunks(kb_doc_id: int, chunks: list[MinedChunk]) -> int:
    """Replace the chunk list for a KB doc. Returns the number of rows
    actually written (chunks whose text is empty after cleaning are
    dropped).

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
            text = _clean_text(c.text).strip()[:4000]
            if not text:
                continue
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
        return len(rows)


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