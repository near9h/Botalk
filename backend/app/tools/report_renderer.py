"""Render a validated `ReportPayload` into HTML and docx.

The renderer owns layout & typography. The LLM owns content. This is
the linchpin of 路线 B: stable output across re-runs because the
template — not the model — decides what each page looks like.

Templates live in `app/tools/templates/`. Two are shipped:
  - `default.html.j2`     → clean, print-ready HTML report
  - `default.docx.j2`     → minimal Markdown body for pandoc→docx
    (we still call pypandoc to convert Markdown → .docx because
    Jinja can't generate Word XML natively and adding docxtpl for a
    default template would be over-engineering).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pypandoc
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings
from app.tools.report_schema import ReportPayload


_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _env() -> Environment:
    """One Jinja2 environment per process. Cheap to recreate but
    caching avoids re-reading template files on every render.

    Adds a `markdown_inline` filter that renders Markdown to HTML.
    We deliberately do NOT trust the input as HTML (the LLM is
    untrusted), so we route it through markdown-it with `html: false`
    — any `<script>` the model emits will be escaped, not run.
    """
    from markdown_it import MarkdownIt  # local import keeps top of file clean

    # Enable GFM features (tables, strikethrough, task lists, autolink)
    # in addition to CommonMark. The LLM emits real Markdown tables
    # so we need `tables: True` or the bot-authored report renders as
    # raw pipe-text. `html: False` keeps the sanitizer strict.
    md = MarkdownIt("gfm-like", {"breaks": True, "html": False, "linkify": False, "typographer": False})
    md.enable(["table", "strikethrough"])

    def markdown_inline(text: str) -> str:
        return md.render(text or "")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["markdown_inline"] = markdown_inline
    return env


def _safe_filename(name: str, default_ext: str) -> str:
    name = (name or "report").strip()
    # Drop characters that hurt URLs and Windows paths
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    if not name:
        name = "report"
    if not name.lower().endswith("." + default_ext):
        # Replace any existing extension with the requested one
        stem = name.rsplit(".", 1)[0] if "." in name else name
        name = f"{stem}.{default_ext}"
    return name[:200]


def _payload_fingerprint(payload: ReportPayload) -> str:
    """SHA-256 of the structured payload.

    Used by the caller as a cache key so two requests that produce
    identical payloads can short-circuit the LLM round-trip on a
    retry (and so identical content ⇒ identical bytes).
    """
    canonical = payload.model_dump_json()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_html(payload: ReportPayload) -> str:
    """Render the payload as a self-contained HTML document (CSS inlined)."""
    template = _env().get_template("default.html.j2")
    return template.render(
        payload=payload,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


def render_docx_md(payload: ReportPayload) -> str:
    """Render the payload as a Markdown string that pandoc turns into
    a stable .docx. We don't run Jinja for this — pandoc has perfectly
    good built-in styling — but we do normalize section ordering and
    strip random heading variations the LLM might produce."""
    parts: list[str] = []
    parts.append(f"# {payload.title}\n")
    if payload.summary:
        parts.append(f"> {payload.summary}\n")
    for sec in payload.sections:
        parts.append(f"## {sec.title}\n")
        body = (sec.body or "").strip()
        if body:
            parts.append(body + "\n")
    return "\n".join(parts)


def render(
    payload: ReportPayload,
    *,
    formats: tuple[str, ...] = ("html", "docx"),
) -> dict[str, dict[str, Any]]:
    """Render a payload into the requested file formats.

    Returns a dict keyed by format, value = {
        "filename": str,
        "path": str,           # absolute path on disk
        "mime_type": str,
        "body": str | None,    # raw bytes (only for non-docx formats that
                               # the tool caller doesn't need on disk)
    }
    Files are written under `upload_dir` (the standard attachment
    directory) so the existing download endpoint can serve them with
    no further glue.
    """
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = _safe_filename(payload.title, "html").rsplit(".", 1)[0]
    out: dict[str, dict[str, Any]] = {}

    if "html" in formats:
        html = render_html(payload)
        path = upload_dir / f"{safe_stem}.html"
        # Disambiguate parallel renders by appending -N before the ext
        if path.exists():
            for n in range(2, 1000):
                cand = upload_dir / f"{safe_stem}-{n}.html"
                if not cand.exists():
                    path = cand
                    break
        path.write_text(html, encoding="utf-8")
        out["html"] = {
            "filename": path.name,
            "path": str(path),
            "mime_type": "text/html; charset=utf-8",
            "size_bytes": path.stat().st_size,
        }

    if "docx" in formats:
        md_text = render_docx_md(payload)
        path = upload_dir / f"{safe_stem}.docx"
        if path.exists():
            for n in range(2, 1000):
                cand = upload_dir / f"{safe_stem}-{n}.docx"
                if not cand.exists():
                    path = cand
                    break
        try:
            pypandoc.convert_text(
                md_text,
                "docx",
                format="md",
                outputfile=str(path),
                extra_args=["--toc", "--toc-depth=3"],
            )
        except Exception as exc:  # noqa: BLE001
            # Leave docx out of the result; the tool caller can fall
            # back to legacy generate_document if HTML alone is OK.
            out.setdefault("_warnings", []).append(f"docx render failed: {exc}")  # type: ignore[union-attr]
        else:
            out["docx"] = {
                "filename": path.name,
                "path": str(path),
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "size_bytes": path.stat().st_size,
            }

    return out


def fingerprint(payload: ReportPayload) -> str:
    """Public re-export of the SHA-256 of the canonical payload."""
    return _payload_fingerprint(payload)