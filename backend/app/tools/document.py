"""Document generation tool.

Two entry points:

1. `generate_document(args, ...)` — legacy "free markdown → docx"
   path. Still works for bots that haven't been migrated to 路线 B,
   and as a safety net when the structured-output parse fails.

2. `generate_document_from_payload(payload, group_id)` — 路线 B path:
   the bot already returned a validated `ReportPayload` JSON object,
   which we render through a Jinja template into HTML + docx, persist
   each as its own `Attachment` row, and return download links.

Why in-tree pandoc? Installing `pandoc` system-wide requires apt or
homebrew on the host, which is fragile inside Docker. `pypandoc-binary`
vendors a prebuilt binary into the image, so the tool works out of the
box without any extra setup step.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pypandoc
from pydantic import ValidationError

from app.config import get_settings
from app.db.models import Attachment
from app.db.session import SessionLocal
from app.tools.report_renderer import render as render_payload
from app.tools.report_schema import ReportPayload, parse_payload

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
            att_token = att.public_id
    except Exception as exc:  # noqa: BLE001
        return f"[generate_document] 写入附件失败: {exc}"

    # Return a self-describing markdown payload that the chat bubble
    # can render as a download card. Keep it terse so the LLM doesn't
    # add any extra text around it.
    title_part = f"（{title}）" if title else ""
    return (
        f"📄 文档已生成{title_part}：`{filename}`  "
        f"[下载](attachment://{att_token})  "
        f"（{size_bytes // 1024} KB）"
    )


async def generate_document_from_payload(
    raw_reply: str,
    group_id: int | None,
    *,
    formats: tuple[str, ...] = ("html", "docx"),
) -> tuple[str, list[str]]:
    """路线 B entry: parse the bot's full reply as a `ReportPayload`,
    render it through Jinja, persist each format as its own
    Attachment row, and return (markdown_summary, [attachment_ids]).

    On parse / validation failure we fall back to the legacy
    `generate_document` path so the caller always gets *something*
    rather than a hard error.
    """
    try:
        payload = parse_payload(raw_reply)
    except (ValidationError, ValueError, json.JSONDecodeError):
        # Treat the whole reply as free markdown and ship the legacy
        # single-docx path. Caller sees the same `📄 ... ` line and
        # the user gets a download.
        md = await generate_document(
            {"markdown": raw_reply, "filename": "report.docx", "group_id": group_id}
        )
        return md, []

    rendered = render_payload(payload, formats=formats)
    if not rendered:
        # Payload parsed but the renderer produced nothing (e.g. zero
        # sections). Surface a friendly hint instead of letting the
        # raw JSON blob leak through to the chat UI.
        return (
            "⚠️ 已解析报告结构，但渲染器未产出任何文件（可能是 sections 为空）。"
            "原始回复保留在历史记录中。",
            [],
        )

    rendered_items = [(fmt, info) for fmt, info in rendered.items() if fmt != "_warnings"]
    att_tokens: list[str] = []
    try:
        async with SessionLocal() as session:
            for _fmt, info in rendered_items:
                att = Attachment(
                    group_id=group_id,
                    filename=info["filename"],
                    mime_type=info["mime_type"],
                    size_bytes=info["size_bytes"],
                    status="done",
                    content_md=None,
                    storage_path=info["path"],
                )
                session.add(att)
            await session.commit()
            # Re-fetch by storage_path to get the assigned public_ids.
            from sqlalchemy import select  # local import keeps module-level clean
            paths = [info["path"] for _fmt, info in rendered_items]
            rows = (
                await session.execute(
                    select(Attachment).where(Attachment.storage_path.in_(paths))
                )
            ).scalars().all()
            att_ids_by_path = {a.storage_path: a.public_id for a in rows}
    except Exception as exc:  # noqa: BLE001
        return f"[generate_document_from_payload] 写入附件失败: {exc}", []

    links: list[str] = []
    for fmt, info in rendered_items:
        att_token = att_ids_by_path.get(info["path"])
        if not att_token:
            continue
        att_tokens.append(att_token)
        size_kb = max(1, info["size_bytes"] // 1024)
        emoji = "🌐" if fmt == "html" else "📄"
        links.append(
            f"{emoji} [{fmt.upper()}](attachment://{att_token})（{size_kb} KB）"
        )

    if not links:
        return "[generate_document_from_payload] 没有可下载的产物", []
    summary = (
        f"📄 文档已生成：**{payload.title}**\n\n"
        + "\n".join(links)
        + f"\n\n_结构化渲染 · {len(payload.sections)} 章节_"
    )
    return summary, att_ids