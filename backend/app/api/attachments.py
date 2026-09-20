"""Attachment upload + MinerU parsing endpoints."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runs import _resolve_visible_group
from app.auth import require_user
from app.config import get_settings
from app.db.models import Attachment, Group, User
from app.db.session import get_session
from app.services import audit as audit_service
from app.services.mineru import parse_pdf

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# Mime types MinerU accepts for its non-HTML parsers.
_ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/msword",  # doc
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
    "application/vnd.ms-powerpoint",  # ppt
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.ms-excel",  # xls
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/jp2",
    "text/html",
    "application/xhtml+xml",
}
# Limit by extension too — clients sometimes send wrong mime for PDFs.
_ALLOWED_EXT = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".jp2",
    ".html",
    ".htm",
}


def _ensure_upload_dir() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.post("")
async def upload_attachment(
    file: UploadFile = File(...),
    group_public_id: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> dict:
    """Upload a PDF (or other MinerU-supported file) and synchronously parse it.

    Returns the attachment record with extracted Markdown inline. Synchronous
    because MinerU parsing takes seconds-to-minutes and the frontend already
    shows a spinner via the upload progress.
    """
    if not settings.mineru_api_key:
        raise HTTPException(
            status_code=503,
            detail="MINERU_API_KEY not configured on the backend",
        )

    # Basic validation by extension (mime is unreliable from browsers).
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{suffix}'. Allowed: "
                + ", ".join(sorted(_ALLOWED_EXT))
            ),
        )

    # Validate group_public_id + 可见性检查（wire-facing 改字符串）
    group_int_id: int | None = None
    if group_public_id:
        grp = await _resolve_visible_group(session, user, group_public_id)
        if grp is None:
            raise HTTPException(
                status_code=400,
                detail=f"group_public_id={group_public_id} 不可见或不存在",
            )
        group_int_id = grp.id

    # Stream file to disk so we can size-check and survive a 200MB upload.
    upload_dir = _ensure_upload_dir()
    # Sanitize the on-disk filename: drop any path separators the
    # browser might have leaked through so the upload can't escape its
    # directory. Keep the original (possibly long) filename for display
    # purposes — that one only goes into the DB column.
    raw = os.path.basename((file.filename or "upload").replace("\\", "/"))
    safe_name = f"{os.getpid()}-{raw}"
    # Cap on-disk filename length so we don't blow past the filesystem
    # NAME_MAX (usually 255 bytes) on long uploads.
    if len(safe_name.encode("utf-8")) > 200:
        safe_name = safe_name.encode("utf-8")[:200].decode("utf-8", "ignore")
    dest = upload_dir / safe_name
    # Belt-and-braces: also cap the mime value to the column width so we
    # never crash with `value too long` if a future migration shrinks it.
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
                        detail=(
                            f"File exceeds {settings.max_upload_bytes // (1024*1024)}MB limit"
                        ),
                    )
                f.write(chunk)
    finally:
        await file.close()

    att = Attachment(
        group_id=group_int_id,
        filename=file.filename or "upload",
        mime_type=mime,
        size_bytes=written,
        status="pending",
        content_md="",
        storage_path=str(dest),
    )
    session.add(att)
    await audit_service.log(
        session,
        ctx,
        action="attachment.upload",
        target_type="attachment",
        target_id=str(att.id),
        target_name=att.filename,
        detail={"size_bytes": att.size_bytes, "group_public_id": group_public_id},
    )
    await session.commit()
    await session.refresh(att)

    # Parse on the event loop — httpx calls are async, fine.
    try:
        with dest.open("rb") as f:
            raw = f.read()
        md = await parse_pdf(file.filename or "upload.pdf", raw)
    except Exception as exc:  # noqa: BLE001
        att.status = "failed"
        att.err_msg = str(exc)[:2000]
        await session.commit()
        await session.refresh(att)
        logger.exception("MinerU parse failed for %s", file.filename)
        # Don't blow away the uploaded file — operators may want to inspect.
        raise HTTPException(
            status_code=502,
            detail=f"MinerU parse failed: {exc}",
        )
    finally:
        # Free disk: keep metadata, drop bytes (we have the Markdown).
        try:
            dest.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        att.storage_path = None

    att.status = "done"
    att.content_md = md
    await session.commit()
    await session.refresh(att)

    return _serialize(att)


async def _resolve_visible_attachment(
    session: AsyncSession, user: User, att_public_id: str
) -> Attachment | None:
    """Return the attachment iff its parent group is visible to `user`.

    An attachment is visible iff:
      * the user is admin,
      * OR its parent group is `system` scope (shared with everyone),
      * OR its parent group is owned by the user.

    For unattached attachments (group_id is NULL — e.g. ad-hoc uploads
    not yet bound to a session) we fall back to admin-only.

    Lookups are keyed by the unguessable `public_id` so the URL path
    can't be enumerated to enumerate other users' attachment IDs.
    """
    result = await session.execute(
        select(Attachment).where(Attachment.public_id == att_public_id)
    )
    att = result.scalar_one_or_none()
    if not att:
        return None
    if att.group_id is None:
        return att if user.role == "admin" else None
    grp = await session.get(Group, att.group_id)
    if grp is None:
        return None
    if (
        user.role == "admin"
        or grp.scope == "system"
        or grp.owner_id == user.id
    ):
        return att
    return None


@router.get("/{att_public_id}")
async def get_attachment(
    att_public_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> dict:
    att = await _resolve_visible_attachment(session, user, att_public_id)
    if not att:
        raise HTTPException(status_code=404, detail="attachment not found")
    return _serialize(att, include_content=True)


@router.get("/{att_public_id}/download")
async def download_attachment(
    att_public_id: str,
    inline: bool = Query(
        default=False,
        description=(
            "If true, send Content-Disposition: inline so the browser "
            "renders the bytes inside an iframe / embedded viewer instead "
            "of saving to disk. Used by the front-end preview drawer."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    """Stream the attachment's bytes as a file download.

    Bot-authored attachments (路线 B / `generate_document`) write the
    actual bytes to `storage_path` on the host filesystem and leave
    `content_md` empty (the file itself *is* the artifact). Legacy
    attachments that pre-date storage on disk may still carry the
    content inline in `content_md` — serve that when present. We never
    want to fall through to "empty body", which is what produced the
    "0 KB 下载" bug when `content_md` was blank but `storage_path`
    pointed at a real file.

    `inline=true` swaps Content-Disposition to `inline` for in-page
    viewers (pdf.js / mammoth / iframe); default is `attachment` so the
    existing download button keeps behaving like a real download.

    Identified by the unguessable `public_id` rather than the integer
    pk so URLs aren't enumerable.
    """
    import urllib.parse
    from pathlib import Path

    att = await _resolve_visible_attachment(session, user, att_public_id)
    if not att:
        raise HTTPException(status_code=404, detail="attachment not found")

    # Prefer the on-disk file (real bytes) over content_md. We still
    # allow content_md as a fallback so legacy uploads / fixtures keep
    # serving from the database.
    body: bytes | None = None
    if att.storage_path:
        try:
            body = Path(att.storage_path).read_bytes()
        except FileNotFoundError:
            # Storage got cleaned up after the upload was parsed.
            # Fall through to content_md; if that's empty too we'll
            # raise a clear error rather than shipping a 0-byte file.
            body = None
    if body is None:
        body = (att.content_md or "").encode("utf-8")
    if not body:
        raise HTTPException(
            status_code=410,
            detail="附件内容已不可用（源文件已被清理）",
        )

    # RFC 5987: the bare filename= part must be ASCII-only (it's sent
    # using latin-1 by browsers), so we fall back to a sanitized
    # ascii-only string when the real filename has non-ASCII chars. The
    # full Unicode name is then conveyed via filename*=UTF-8''.
    ascii_name = att.filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    if not ascii_name:
        ascii_name = "download"
    quoted = urllib.parse.quote(att.filename, safe="")
    disposition_kind = "inline" if inline else "attachment"
    return Response(
        content=body,
        media_type=att.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"{disposition_kind}; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{quoted}"
            ),
            "Content-Length": str(len(body)),
        },
    )


@router.get("")
async def list_attachments(
    group_public_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[dict]:
    """List attachments, optionally filtered by `group_public_id`.

    普通用户传一个不可见的 group_public_id 会拿到空列表。
    """
    group_int_id: int | None = None
    if group_public_id:
        grp = await _resolve_visible_group(session, user, group_public_id)
        if grp is None:
            return []
        group_int_id = grp.id
    q = select(Attachment)
    if group_int_id is not None:
        q = q.where(Attachment.group_id == group_int_id)
    q = q.order_by(Attachment.created_at.desc())
    result = await session.execute(q)
    return [_serialize(a, include_content=False) for a in result.scalars().all()]


@router.post("/batch-meta")
async def batch_attachment_meta(
    public_ids: list[str],
    session: AsyncSession = Depends(get_session),
    # Fix for security audit item AC1: this endpoint was missing the
    # `require_user` dependency, so unauthenticated callers could probe
    # attachment metadata. Even though only public_ids (not enum-able
    # ints) are accepted, anonymous metadata reads are not part of the
    # intended threat model.
    user: User = Depends(require_user),
) -> list[dict]:
    """Return lightweight metadata (no content) for a list of attachment public_ids.

    Used by the chat bubble to render download cards when scrolling
    through historical messages (where the SSE payload is no longer
    available). public_ids that don't exist are silently skipped.

    Note: this endpoint intentionally accepts only `public_id`s so the
    server can validate them against the indexed column. Callers that
    have only an integer id should use the public_id field returned by
    the upload/list endpoints instead.
    """
    if not public_ids:
        return []
    # De-dup + cap to a reasonable batch so a misbehaving caller can't
    # query thousands of rows in one shot.
    seen: set[str] = set()
    wanted: list[str] = []
    for x in public_ids:
        if isinstance(x, str) and x and x not in seen:
            seen.add(x)
            wanted.append(x)
            if len(wanted) >= 200:
                break
    result = await session.execute(
        select(Attachment).where(Attachment.public_id.in_(wanted))
    )
    return [_serialize(a, include_content=False) for a in result.scalars().all()]


def _serialize(att: Attachment, *, include_content: bool = True) -> dict:
    out: dict = {
        # `public_id` is the unguessable token used in all URLs the
        # client renders. We keep the integer `id` for callers that
        # need it for internal joins (e.g. audit log targets).
        "id": att.id,
        "public_id": att.public_id,
        "group_id": att.group_id,
        "filename": att.filename,
        "mime_type": att.mime_type,
        "size_bytes": att.size_bytes,
        "status": att.status,
        "err_msg": att.err_msg,
        "created_at": att.created_at.isoformat() if att.created_at else None,
    }
    if include_content:
        out["content_md"] = att.content_md
    else:
        # Truncated preview so list payloads stay small.
        out["content_preview"] = (att.content_md or "")[:500]
        out["content_chars"] = len(att.content_md or "")
    return out