"""Knowledge base CRUD + upload endpoints (路线 RAG).

Surface area:

  GET    /api/kb                  list KBs the caller can mount on bots
  POST   /api/kb                  create a new KB (owner = caller)
  GET    /api/kb/{kb_id}          KB metadata + doc count
  DELETE /api/kb/{kb_id}          delete KB + cascade documents + chunks

  GET    /api/kb/{kb_id}/documents            list documents in a KB
  POST   /api/kb/{kb_id}/documents            upload + enqueue ingest
  GET    /api/kb/{kb_id}/documents/{doc_id}   single doc + status + chunks
  DELETE /api/kb/{kb_id}/documents/{doc_id}   drop doc (also drops chunks)

  GET    /api/kb/{kb_id}/chunks/{chunk_id}     bbox + snippet (used by
                                                the PDF.js viewer for
                                                highlights)

The upload pipeline is `multipart/form-data` and reuses the same
byte-level guardrails as `attachments.upload_attachment` (size cap,
mime allowlist). After the file lands on disk we create an Attachment
row with group_id=NULL (KB docs aren't chat attachments) and an
empty KbDocument, then schedule the ingest worker. The client polls
`GET /api/kb/{kb_id}/documents/{doc_id}` to track `pending → parsing
→ ready / failed`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_user
from app.config import get_settings
from app.db.models import Attachment, KbChunk, KbDocument, KnowledgeBase, User
from app.db.session import get_session
from app.services import audit as audit_service
from app.services import ragflow_client
from app.workers import ingest_worker

router = APIRouter()
settings = get_settings()


# ─────────────────────────── schemas ───────────────────────────


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    is_public: bool = False


class KbOut(BaseModel):
    id: int
    name: str
    description: str
    is_public: bool
    ragflow_dataset_id: str | None
    created_at: str

    @classmethod
    def from_row(cls, kb: KnowledgeBase) -> "KbOut":
        return cls(
            id=kb.id,
            name=kb.name,
            description=kb.description or "",
            is_public=kb.is_public,
            ragflow_dataset_id=kb.ragflow_dataset_id,
            created_at=kb.created_at.isoformat() if kb.created_at else "",
        )


class KbDocumentOut(BaseModel):
    id: int
    kb_id: int
    attachment_id: int
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    error: str
    chunk_count: int
    ragflow_doc_id: str | None
    created_at: str

    @classmethod
    def from_row(cls, d: KbDocument, att: Attachment) -> "KbDocumentOut":
        return cls(
            id=d.id,
            kb_id=d.kb_id,
            attachment_id=d.attachment_id,
            filename=att.filename,
            mime_type=att.mime_type or "",
            size_bytes=att.size_bytes,
            status=d.status,
            error=d.error or "",
            chunk_count=d.chunk_count,
            ragflow_doc_id=d.ragflow_doc_id,
            created_at=d.created_at.isoformat() if d.created_at else "",
        )


class KbChunkOut(BaseModel):
    id: int
    kb_doc_id: int
    ragflow_chunk_id: str | None
    page: int | None
    para: int | None
    bbox_json: list | None
    snippet: str

    @classmethod
    def from_row(cls, c: KbChunk) -> "KbChunkOut":
        return cls(
            id=c.id,
            kb_doc_id=c.kb_doc_id,
            ragflow_chunk_id=c.ragflow_chunk_id,
            page=c.page,
            para=c.para,
            bbox_json=list(c.bbox_json) if c.bbox_json else None,
            snippet=c.snippet or "",
        )


# ─────────────────────────── helpers ───────────────────────────


async def _resolve_kb(
    session: AsyncSession, kb_id: int, user: User
) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    # Visibility:
    #   admin → all
    #   scope=system → everyone
    #   is_public=True → everyone can read + mount
    #   owner → can read + write
    if user.role == "admin" or kb.scope == "system":
        return kb
    if kb.is_public:
        return kb
    if kb.owner_id == user.id:
        return kb
    raise HTTPException(status_code=404, detail="knowledge base not found")


def _can_modify(kb: KnowledgeBase, user: User) -> bool:
    if user.role == "admin":
        return True
    if kb.scope == "system":
        return user.role == "admin"
    return kb.owner_id == user.id


def _ensure_upload_dir() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─────────────────────────── KB CRUD ───────────────────────────


@router.get("", response_model=list[KbOut])
async def list_kbs(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[KbOut]:
    """All KBs the caller can mount on a bot. Sorted by name."""
    stmt = select(KnowledgeBase).order_by(KnowledgeBase.name.asc())
    rows = (await session.execute(stmt)).scalars().all()
    out: list[KbOut] = []
    for kb in rows:
        if user.role == "admin" or kb.scope == "system" or kb.is_public:
            out.append(KbOut.from_row(kb))
            continue
        if kb.owner_id == user.id:
            out.append(KbOut.from_row(kb))
    return out


@router.post("", response_model=KbOut, status_code=201)
async def create_kb(
    payload: KbCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> KbOut:
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="name cannot be blank")
    kb = KnowledgeBase(
        name=payload.name.strip(),
        description=payload.description,
        owner_id=user.id,
        scope="user",
        is_public=payload.is_public,
    )
    session.add(kb)
    # Flush so the kb.id is generated before we record the audit row;
    # otherwise target_id would have to be filled after commit (which
    # the audit log helper doesn't support — it shares the same
    # session/transaction as the kb insert).
    await session.flush()
    await audit_service.log(
        session, ctx,
        action="kb.create",
        target_type="kb",
        target_id=str(kb.id),
        target_name=kb.name,
        detail={"is_public": kb.is_public},
    )
    await session.commit()
    await session.refresh(kb)
    return KbOut.from_row(kb)


@router.get("/{kb_id}", response_model=KbOut)
async def get_kb(
    kb_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> KbOut:
    kb = await _resolve_kb(session, kb_id, user)
    return KbOut.from_row(kb)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    kb = await _resolve_kb(session, kb_id, user)
    if not _can_modify(kb, user):
        raise HTTPException(status_code=403, detail="无权删除该知识库")
    # Drop the RAGFlow dataset first so the engine doesn't carry stale
    # state. Failure here is non-fatal — the engine's garbage collector
    # will eventually clean it up; we still drop the local rows.
    if ragflow_client.is_configured() and kb.ragflow_dataset_id:
        try:
            client = await ragflow_client.get_client()
            await client.delete_dataset(kb.ragflow_dataset_id)
        except Exception as exc:  # noqa: BLE001
            from app.api.kb import logger  # local import keeps top tidy
            logger.warning(
                "RAGFlow dataset delete failed for kb=%s dataset=%s: %s",
                kb_id, kb.ragflow_dataset_id, exc,
            )
    name = kb.name
    await session.delete(kb)
    await audit_service.log(
        session, ctx,
        action="kb.delete",
        target_type="kb",
        target_id=str(kb_id),
        target_name=name,
    )
    await session.commit()


# ─────────────────────────── Documents ───────────────────────────


@router.get("/{kb_id}/documents", response_model=list[KbDocumentOut])
async def list_kb_documents(
    kb_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[KbDocumentOut]:
    kb = await _resolve_kb(session, kb_id, user)
    rows = (
        await session.execute(
            select(KbDocument, Attachment)
            .join(Attachment, Attachment.id == KbDocument.attachment_id)
            .where(KbDocument.kb_id == kb.id)
            .order_by(KbDocument.created_at.desc())
        )
    ).all()
    return [KbDocumentOut.from_row(d, a) for d, a in rows]


@router.post(
    "/{kb_id}/documents",
    response_model=KbDocumentOut,
    status_code=201,
)
async def upload_kb_document(
    kb_id: int,
    file: Annotated[UploadFile, File(...)],
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> KbDocumentOut:
    """Upload a PDF/Word/Excel/FAQ to a KB and enqueue ingestion."""
    kb = await _resolve_kb(session, kb_id, user)
    if not _can_modify(kb, user):
        raise HTTPException(status_code=403, detail="无权修改该知识库")
    if not settings.mineru_api_key:
        raise HTTPException(
            status_code=503,
            detail="MINERU_API_KEY not configured on the backend",
        )

    suffix = Path(file.filename or "upload").suffix.lower()
    allowed_ext = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
                   ".txt", ".md", ".markdown", ".html", ".htm"}
    if suffix not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'",
        )

    # Stream to disk with the same 200 MB cap as the chat upload.
    upload_dir = _ensure_upload_dir()
    raw = os.path.basename((file.filename or "upload").replace("\\", "/"))
    safe_name = f"{os.getpid()}-{raw}"
    if len(safe_name.encode("utf-8")) > 200:
        safe_name = safe_name.encode("utf-8")[:200].decode("utf-8", "ignore")
    dest = upload_dir / f"kb-{kb_id}-{safe_name}"
    mime = (file.content_type or "application/octet-stream")[:128]
    written = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {settings.max_upload_bytes // (1024*1024)}MB limit",
                    )
                f.write(chunk)
    finally:
        await file.close()

    # KB documents are detached from any chat group — group_id stays
    # NULL so the public upload port and chat attachments list don't
    # surface them.
    att = Attachment(
        group_id=None,
        filename=file.filename or "upload",
        mime_type=mime,
        size_bytes=written,
        status="pending",
        content_md="",
        storage_path=str(dest),
    )
    session.add(att)
    await session.flush()  # populate att.id
    kb_doc = KbDocument(
        kb_id=kb.id,
        attachment_id=att.id,
        status="pending",
    )
    session.add(kb_doc)
    await audit_service.log(
        session, ctx,
        action="kb.doc.upload",
        target_type="kb_document",
        target_id=str(kb_doc.id),
        target_name=file.filename or "upload",
        detail={"kb_id": kb.id, "size_bytes": written},
    )
    await session.commit()
    await session.refresh(kb_doc)
    await session.refresh(att)

    # Kick off async ingest. The worker handles its own failure
    # reporting (status -> failed) so we don't block the upload API
    # on a multi-minute MinerU round-trip.
    ingest_worker.enqueue(kb_doc.id)
    return KbDocumentOut.from_row(kb_doc, att)


@router.get(
    "/{kb_id}/documents/{doc_id}",
    response_model=KbDocumentOut,
)
async def get_kb_document(
    kb_id: int,
    doc_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> KbDocumentOut:
    kb = await _resolve_kb(session, kb_id, user)
    row = (
        await session.execute(
            select(KbDocument, Attachment)
            .join(Attachment, Attachment.id == KbDocument.attachment_id)
            .where(KbDocument.id == doc_id, KbDocument.kb_id == kb.id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="document not found")
    d, a = row
    return KbDocumentOut.from_row(d, a)


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    status_code=204,
)
async def delete_kb_document(
    kb_id: int,
    doc_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    kb = await _resolve_kb(session, kb_id, user)
    if not _can_modify(kb, user):
        raise HTTPException(status_code=403, detail="无权修改该知识库")
    row = (
        await session.execute(
            select(KbDocument, Attachment)
            .join(Attachment, Attachment.id == KbDocument.attachment_id)
            .where(KbDocument.id == doc_id, KbDocument.kb_id == kb.id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="document not found")
    d, a = row
    name = a.filename
    # Best-effort: also drop from RAGFlow. Failure is non-fatal; the
    # engine garbage-collects datasets that don't have any chunks left.
    if ragflow_client.is_configured() and kb.ragflow_dataset_id and d.ragflow_doc_id:
        try:
            client = await ragflow_client.get_client()
            await client.delete_document(kb.ragflow_dataset_id, d.ragflow_doc_id)
        except Exception:  # noqa: BLE001
            from app.api.kb import logger
            logger.warning("RAGFlow doc delete failed for %s", d.ragflow_doc_id)
    await session.delete(d)  # cascades to kb_chunks
    await session.delete(a)
    await audit_service.log(
        session, ctx,
        action="kb.doc.delete",
        target_type="kb_document",
        target_id=str(doc_id),
        target_name=name,
        detail={"kb_id": kb.id},
    )
    await session.commit()


# ─────────────────────────── Chunks (read-only) ───────────────────────────


@router.get(
    "/{kb_id}/documents/{doc_id}/chunks",
    response_model=list[KbChunkOut],
)
async def list_kb_document_chunks(
    kb_id: int,
    doc_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[KbChunkOut]:
    """List every chunk attached to one KB document, ordered by page
    then paragraph. Drives the KB-detail page's chunk preview.

    Registered *before* the more specific `/{kb_id}/chunks/{chunk_id}`
    route below — FastAPI matches routes in declaration order, and the
    longer prefix would otherwise eat the `/documents/{doc_id}/chunks`
    URL pattern.
    """
    kb = await _resolve_kb(session, kb_id, user)
    doc = await session.get(KbDocument, doc_id)
    if not doc or doc.kb_id != kb.id:
        raise HTTPException(status_code=404, detail="document not found")
    rows = (
        await session.execute(
            select(KbChunk)
            .where(KbChunk.kb_doc_id == doc.id)
            .order_by(
                KbChunk.page.is_(None),
                KbChunk.page.asc(),
                KbChunk.para.is_(None),
                KbChunk.para.asc(),
                KbChunk.id.asc(),
            )
        )
    ).scalars().all()
    return [KbChunkOut.from_row(c) for c in rows]


@router.get(
    "/{kb_id}/chunks/{chunk_id}",
    response_model=KbChunkOut,
)
async def get_kb_chunk(
    kb_id: int,
    chunk_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> KbChunkOut:
    """Fetch one chunk's bbox + snippet. Used by the chat UI's PDF.js
    viewer to draw the highlight overlay after a user clicks a
    citation chip."""
    kb = await _resolve_kb(session, kb_id, user)
    chunk = await session.get(KbChunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="chunk not found")
    # FK chain: chunk → kb_document → kb, so we walk back up via the
    # relationship to make sure the chunk belongs to the KB the caller
    # resolved.
    doc = await session.get(KbDocument, chunk.kb_doc_id)
    if not doc or doc.kb_id != kb.id:
        raise HTTPException(status_code=404, detail="chunk not found")
    return KbChunkOut.from_row(chunk)


# Tiny shim logger so the delete_kb warning above has somewhere to land.
import logging
logger = logging.getLogger(__name__)