"""Document generation tool.

`generate_document(markdown, filename, title=None)` — turn a piece of
markdown into a real `.docx` (using an in-tree pandoc binary), persist it
as an attachment, and return a download link so the frontend can render
a download card in the chat bubble.

Why in-tree pandoc? Installing `pandoc` system-wide requires apt or
homebrew on the host, which is fragile inside Docker. `pypandoc-binary`
vendors a prebuilt binary into the image, so the tool works out of the
box without any extra setup step.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pypandoc

from app.config import get_settings
from app.db.models import Attachment
from app.db.session import SessionLocal

_INVALID_FN = re.compile(r"[\\/:*?\"<>|]+")


def _safe_filename(name: str) -> str:
    """Sanitize the user-supplied filename and ensure it ends in .docx."""
    name = (name or "document").strip()
    name = _INVALID_FN.sub("_", name)
    if not name:
        name = "document"
    if not name.lower().endswith(".docx"):
        name = name + ".docx"
    return name[:200]


async def generate_document(args: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    markdown = (args.get("markdown") or args.get("content") or "").strip()
    if not markdown:
        return "[generate_document] markdown/content 为空，未生成任何文件"
    filename = _safe_filename(args.get("filename") or "document.docx")
    title = (args.get("title") or "").strip() or None
    group_id = args.get("group_id")
    if group_id is not None and not isinstance(group_id, int):
        group_id = None

    # pypandoc with output to .docx has to write to a file (the pandoc
    # binary itself requires --output). Pick a fresh temp path inside the
    # upload dir so we can both persist it as an attachment and serve the
    # download with zero extra copying.
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / filename

    # If the file already exists, disambiguate with a numeric suffix so
    # concurrent calls don't trample each other's output.
    if dest.exists():
        stem = dest.stem
        suf = dest.suffix
        for n in range(2, 1000):
            cand = upload_dir / f"{stem}-{n}{suf}"
            if not cand.exists():
                dest = cand
                filename = dest.name
                break

    try:
        pypandoc.convert_text(
            markdown,
            "docx",
            format="md",
            outputfile=str(dest),
            extra_args=[
                "--toc",  # include a Table of Contents at the top
                "--toc-depth=3",
            ],
        )
    except Exception as exc:  # noqa: BLE001
        return f"[generate_document] pandoc 转换失败: {exc}"

    # Persist as an attachment so the user can download it from the chat
    # bubble (and re-download later via the API).
    try:
        size_bytes = dest.stat().st_size
        async with SessionLocal() as session:
            att = Attachment(
                group_id=group_id,
                filename=filename,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size_bytes=size_bytes,
                status="done",
                content_md=markdown,
                storage_path=str(dest),
            )
            session.add(att)
            await session.commit()
            await session.refresh(att)
            att_id = att.id
    except Exception as exc:  # noqa: BLE001
        return f"[generate_document] 写入附件失败: {exc}"

    # Return a self-describing markdown payload that the chat bubble
    # can render as a download card. Keep it terse so the LLM doesn't
    # add any extra text around it.
    title_part = f"（{title}）" if title else ""
    return (
        f"📄 文档已生成{title_part}：`{filename}`  "
        f"[下载](attachment://{att_id})  "
        f"（{size_bytes // 1024} KB）"
    )