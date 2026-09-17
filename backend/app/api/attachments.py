"""Attachment upload + MinerU parsing endpoints."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Attachment, Group
from app.db.session import get_session
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
    group_id: int | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
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

    # Validate group_id up front so we return a clean 400 instead of a
    # generic 500 with a Postgres foreign-key traceback when the caller
    # (e.g. a stale frontend cache) references a deleted group.
    if group_id is not None:
        grp = await session.get(Group, group_id)
        if grp is None:
            raise HTTPException(
                status_code=400,
                detail=f"group_id={group_id} does not exist; refresh the group list",
            )

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
        group_id=group_id,
        filename=file.filename or "upload",
        mime_type=mime,
        size_bytes=written,
        status="pending",
        content_md="",
        storage_path=str(dest),
    )
    session.add(att)
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


@router.get("/{att_id}")
async def get_attachment(
    att_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    result = await session.execute(select(Attachment).where(Attachment.id == att_id))
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="attachment not found")
    return _serialize(att, include_content=True)


@router.get("/{att_id}/download")
async def download_attachment(
    att_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    """Stream the attachment's bytes as a file download.

    Bot-authored attachments store their content in `content_md` (not
    on disk), so we synthesize the body from there. User-uploaded
    attachments have already had their storage_path nulled after
    MinerU parsing — for those we still return content_md when
    available, otherwise an empty body (the upload is consumed).
    """
    import urllib.parse

    att = await session.get(Attachment, att_id)
    if not att:
        raise HTTPException(status_code=404, detail="attachment not found")

    body = (att.content_md or "").encode("utf-8")
    # RFC 5987: the bare filename= part must be ASCII-only (it's sent
    # using latin-1 by browsers), so we fall back to a sanitized
    # ascii-only string when the real filename has non-ASCII chars. The
    # full Unicode name is then conveyed via filename*=UTF-8''.
    ascii_name = att.filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    if not ascii_name:
        ascii_name = "download"
    quoted = urllib.parse.quote(att.filename, safe="")
    return Response(
        content=body,
        media_type=att.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                "attachment; filename=\"" + ascii_name + "\"; "
                "filename*=UTF-8''" + quoted
            ),
        },
    )


@router.get("")
async def list_attachments(
    group_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    q = select(Attachment)
    if group_id is not None:
        q = q.where(Attachment.group_id == group_id)
    q = q.order_by(Attachment.created_at.desc())
    result = await session.execute(q)
    return [_serialize(a, include_content=False) for a in result.scalars().all()]


@router.post("/batch-meta")
async def batch_attachment_meta(
    ids: list[int], session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """Return lightweight metadata (no content) for a list of attachment IDs.

    Used by the chat bubble to render download cards when scrolling
    through historical messages (where the SSE payload is no longer
    available). IDs that don't exist are silently skipped.
    """
    if not ids:
        return []
    # De-dup + cap to a reasonable batch so a misbehaving caller can't
    # query thousands of rows in one shot.
    seen: set[int] = set()
    wanted: list[int] = []
    for x in ids:
        if isinstance(x, int) and x > 0 and x not in seen:
            seen.add(x)
            wanted.append(x)
            if len(wanted) >= 200:
                break
    result = await session.execute(
        select(Attachment).where(Attachment.id.in_(wanted))
    )
    return [_serialize(a, include_content=False) for a in result.scalars().all()]


def _serialize(att: Attachment, *, include_content: bool = True) -> dict:
    out: dict = {
        "id": att.id,
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