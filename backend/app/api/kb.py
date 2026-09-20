"""Knowledge base CRUD + upload endpoints (路线 RAG).

Surface area:

  GET    /api/kb                  list KBs the caller can mount on bots
  POST   /api/kb                  create a new KB (owner = caller)
  GET    /api/kb/{kb_id}          KB metadata + doc count
  PATCH  /api/kb/{kb_id}          partial update (rename today)
  DELETE /api/kb/{kb_id}          delete KB + cascade documents + chunks

  GET    /api/kb/{kb_id}/documents            list documents in a KB
  POST   /api/kb/{kb_id}/documents            upload + enqueue ingest
  GET    /api/kb/{kb_id}/documents/{doc_id}   single doc + status + chunks
  GET    /api/kb/{kb_id}/documents/{doc_id}/preview  内联预览用 PDF
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
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_user
from app.config import get_settings
from app.db.models import Attachment, KbChunk, KbDocument, KnowledgeBase, User
from app.db.session import get_session
from app.services import audit as audit_service
from app.services import office_pdf
from app.services import ragflow_client
from app.workers import ingest_worker

router = APIRouter()
settings = get_settings()


# ─────────────────────────── schemas ───────────────────────────


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    is_public: bool = False


class KbUpdate(BaseModel):
    """Patch-only schema for `PATCH /api/kb/{kb_id}`.

    All fields optional so a future caller can rename + change
    description in a single round-trip without us having to add fields
    one by one. Today only `name` is exposed in the UI; the others are
    here for consistency and forward-compat (server-side guard: ignore
    fields the caller didn't ask for in this release).
    """
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    is_public: bool | None = None


class KbOut(BaseModel):
    # `id` is kept around for the KB list sort + debugging; callers
    # routing by URL or API path should use `public_id` exclusively.
    id: int
    public_id: str
    name: str
    description: str
    is_public: bool
    ragflow_dataset_id: str | None
    # Number of docs that finished ingest (status="ready"). Used by the
    # KB list page to surface "本地检索就绪" without an extra round-trip.
    ready_doc_count: int = 0
    created_at: str

    @classmethod
    def from_row(cls, kb: KnowledgeBase, *, ready_doc_count: int = 0) -> "KbOut":
        return cls(
            id=kb.id,
            public_id=kb.public_id,
            name=kb.name,
            ready_doc_count=ready_doc_count,
            description=kb.description or "",
            is_public=kb.is_public,
            ragflow_dataset_id=kb.ragflow_dataset_id,
            created_at=kb.created_at.isoformat() if kb.created_at else "",
        )


class KbDocumentOut(BaseModel):
    id: int
    kb_id: int
    attachment_id: int
    public_id: str | None = None  # wire-facing id used by /api/attachments/{public_id}/download
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
            public_id=att.public_id,
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
    session: AsyncSession, kb_public_id: str, user: User
) -> KnowledgeBase:
    """Look up a KB by its wire-facing `public_id`.

    Mirrors the same shift we did for groups and attachments: the URL
    path takes the unguessable token, not the integer pk. We still
    return 404 on missing/unauthorized to avoid leaking the existence
    of private KBs to non-owners.
    """
    result = await session.execute(
        select(KnowledgeBase).where(KnowledgeBase.public_id == kb_public_id)
    )
    kb = result.scalar_one_or_none()
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
    visible = [
        kb for kb in rows
        if user.role == "admin" or kb.scope == "system"
        or kb.is_public or kb.owner_id == user.id
    ]
    if not visible:
        return []
    # Aggregate ready-doc counts in one round-trip so the UI can show
    # "本地检索就绪" vs "尚未就绪" without paging docs for each row.
    ids = [kb.id for kb in visible]
    ready_counts: dict[int, int] = {}
    counts_q = await session.execute(
        select(KbDocument.kb_id, func.count(KbDocument.id))
        .where(KbDocument.kb_id.in_(ids), KbDocument.status == "ready")
        .group_by(KbDocument.kb_id)
    )
    for kb_id, n in counts_q.all():
        ready_counts[kb_id] = int(n)
    return [
        KbOut.from_row(kb, ready_doc_count=ready_counts.get(kb.id, 0))
        for kb in visible
    ]


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
        public_id=secrets.token_urlsafe(16),
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
    kb_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> KbOut:
    kb = await _resolve_kb(session, kb_id, user)
    return KbOut.from_row(kb)


@router.patch("/{kb_id}", response_model=KbOut)
async def update_kb(
    kb_id: str,
    payload: KbUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> KbOut:
    """部分更新 KB（rename 等）。

    只在本次发布里接受 `name` 字段（用户界面只展示重命名）。
    `description` / `is_public` 已在 schema 里留位但服务端忽略，避免
    在还没有 UI 的情况下被人误用。

    Rename 受 `_can_modify` 保护：仅 owner / admin 可改；scope=system
    的 KB 只有 admin 能动。前端 kb 列表页拿到的是经过可见性过滤的
    集合，正常情况下操作的就是用户自己的 KB。
    """
    kb = await _resolve_kb(session, kb_id, user)
    if not _can_modify(kb, user):
        raise HTTPException(status_code=403, detail="无权修改该知识库")

    # 没有任何字段更新 → 当作 no-op 返回（避免被滥用做存活探测）。
    if payload.name is None and payload.description is None and payload.is_public is None:
        raise HTTPException(status_code=400, detail="no fields to update")

    changes: dict[str, object] = {}
    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=422, detail="name cannot be blank")
        if new_name != kb.name:
            kb.name = new_name
            changes["name"] = new_name
    # description / is_public 暂时不接 —— 等 UI 跟上后移除此注释
    # 并真正写入。
    # if payload.description is not None:
    #     ...
    # if payload.is_public is not None:
    #     ...

    if changes:
        await audit_service.log(
            session, ctx,
            action="kb.update",
            target_type="kb",
            target_id=str(kb.id),
            target_name=kb.name,
            detail=changes,
        )
    await session.commit()
    await session.refresh(kb)
    return KbOut.from_row(kb)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: str,
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
        target_id=str(kb.id),
        target_name=name,
    )
    await session.commit()


# ─────────────────────────── Documents ───────────────────────────


@router.get("/{kb_id}/documents", response_model=list[KbDocumentOut])
async def list_kb_documents(
    kb_id: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KbDocumentOut]:
    """知识库下的文档列表，按 `created_at DESC` 排序。

    支持分页：默认每页 20 条、上限 200；响应头 `X-Total-Count` 给出可见总数。
    """
    kb = await _resolve_kb(session, kb_id, user)
    base = (
        select(KbDocument, Attachment)
        .join(Attachment, Attachment.id == KbDocument.attachment_id)
        .where(KbDocument.kb_id == kb.id)
    )
    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    if total == 0 or offset >= total:
        return []
    rows = (
        await session.execute(
            base.order_by(KbDocument.created_at.desc()).offset(offset).limit(limit)
        )
    ).all()
    return [KbDocumentOut.from_row(d, a) for d, a in rows]


@router.post(
    "/{kb_id}/documents",
    response_model=KbDocumentOut,
    status_code=201,
)
async def upload_kb_document(
    kb_id: str,
    file: Annotated[UploadFile, File(...)],
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> KbDocumentOut:
    """Upload a PDF/Word/Excel/FAQ to a KB and enqueue ingestion.

    非 PDF 的 Office 文件（doc/docx/ppt/pptx/xls/xlsx）会先由 LibreOffice 转成
    PDF 再存为文档 —— 这样 MinerU 能给出真正的分页和逐块 bbox（引用可高亮），
    浏览器也能直接预览。转换失败会直接返回 422，不会落一条不可预览的记录。
    """
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

    # 非 PDF 的 Office 文件在入库前先转成 PDF，之后整条链路只认 PDF：
    #   - MinerU 拿到 PDF 才会回真正的分页 + 逐块 bbox，引用才能高亮；
    #   - 浏览器可以直接预览，不用再依赖运行时转换；
    #   - chunk 的 page / para 才有意义。
    # 转换失败就直接返回错误，不做「先存原文件、回头再补」——那样文档会处于
    # 一个既不能预览、解析质量又差的中间态。
    stored_path = dest
    stored_name = file.filename or "upload"
    stored_bytes = written
    if office_pdf.needs_pdf_rendition(stored_name):
        pdf_path = dest.with_suffix(".pdf")
        try:
            await office_pdf.convert_to_pdf(dest, pdf_path)
        except RuntimeError as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # 转换成功后原文件就没有用了（PDF 已经承载了全部内容），
        # 留着只会占盘并让 KB 里出现同名的两份文档。
        dest.unlink(missing_ok=True)
        stored_path = pdf_path
        stored_name = f"{Path(stored_name).stem}.pdf"
        stored_bytes = pdf_path.stat().st_size
        mime = "application/pdf"

    # KB documents are detached from any chat group — group_id stays
    # NULL so the public upload port and chat attachments list don't
    # surface them.
    att = Attachment(
        group_id=None,
        filename=stored_name,
        mime_type=mime,
        size_bytes=stored_bytes,
        status="pending",
        content_md="",
        storage_path=str(stored_path),
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
        session,
        ctx,
        action="kb.doc.upload",
        target_type="kb_document",
        target_id=str(kb_doc.id),
        target_name=stored_name,
        detail={
            "kb_id": kb.id,
            "size_bytes": stored_bytes,
            # 保留原始后缀，方便日后排查「这份 PDF 是从什么转来的」。
            "source_suffix": suffix,
        },
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
    kb_id: str,
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


@router.get(
    "/{kb_id}/documents/{doc_id}/preview",
    response_class=FileResponse,
)
async def get_kb_document_preview(
    kb_id: str,
    doc_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    """把 KB 文档当作可在浏览器内联打开的 PDF 返回。

    - 源文件本来就是 PDF → 直接回原文件；
    - Word / PPT / Excel → 由 LibreOffice 转成 PDF 再回（结果落盘缓存，
      后续请求直接命中，见 `services.office_pdf`）；
    - 其它格式 → 415，前端据此提示「暂不支持在线预览」。

    之所以统一成一个入口：前端不需要再各自判断 mime / public_id，
    pdf.js 永远拿到 PDF 字节。
    """
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
    _d, a = row
    src = Path(a.storage_path or "")
    if not src.exists():
        raise HTTPException(status_code=404, detail="源文件已丢失")

    suffix = Path(a.filename or "").suffix.lower()
    if suffix == ".pdf" or (a.mime_type or "").lower() == "application/pdf":
        return FileResponse(src, media_type="application/pdf")

    if not office_pdf.needs_pdf_rendition(a.filename or ""):
        raise HTTPException(
            status_code=415,
            detail=f"暂不支持在线预览 {a.filename}（仅 PDF / Word / PPT / Excel 可预览）",
        )

    try:
        pdf = await office_pdf.ensure_pdf(src, str(a.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(pdf, media_type="application/pdf")


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    status_code=204,
)
async def delete_kb_document(
    kb_id: str,
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
    # 顺手清掉 LibreOffice 派生的预览 PDF，否则会一直占盘。
    office_pdf.drop_cache(Path(a.storage_path or ""), str(a.id))
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
    kb_id: str,
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
    kb_id: str,
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