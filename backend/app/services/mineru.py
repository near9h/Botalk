"""MinerU PDF parser integration.

Flow (batch-mode, server-side upload):
  1. POST /api/v4/file-urls/batch  → {batch_id, file_urls[]}
  2. PUT  file_urls[0]  (the PDF bytes)
  3. GET  /api/v4/extract-results/batch/{batch_id}  → polls until
     per-file state is `done` or `failed`. Each entry has `full_zip_url`.
  4. Download the zip, unzip, read `full.md`.

For the KB ingest pipeline we also read `layout.json` from the same
zip — MinerU emits one block per page with `bbox` (x1, y1, x2, y2,
**origin at the page's top-left corner, y axis pointing down**) and
`page_number`. We use that to populate `kb_chunks.bbox_json` so the
chat UI can highlight the original PDF when a citation fires.

Note the origin: pdf.js `getViewport({scale: 1})` uses the same
top-left/down convention, so the frontend viewer only needs to
multiply by its render scale — it must NOT flip y.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE = "https://mineru.net/api/v4"


@dataclass
class MinedChunk:
    """One block extracted from a PDF by MinerU.

    `text` is the block's plain text content. `bbox` is the rectangle in
    PDF user-space coordinates — pdf.js takes these raw, no scaling
    needed. `page` is 1-indexed; `block_id` is MinerU's per-page block
    index (useful for de-dup when chunks overlap).
    """

    block_id: int
    page: int
    text: str
    bbox: list[float]  # [x1, y1, x2, y2]

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page": self.page,
            "text": self.text,
            "bbox": list(self.bbox),
        }


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.mineru_api_key}",
        "Content-Type": "application/json",
    }


async def _request_upload_url(
    client: httpx.AsyncClient, filename: str, data_id: str
) -> tuple[str, str]:
    """Step 1+2: ask for a batch upload slot, then PUT the file. Returns batch_id."""
    if not settings.mineru_api_key:
        raise RuntimeError("MINERU_API_KEY not configured on backend")

    resp = await client.post(
        f"{BASE}/file-urls/batch",
        headers=_headers(),
        json={
            "files": [{"name": filename, "data_id": data_id}],
            "model_version": settings.mineru_model_version,
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") not in (0, 200):
        raise RuntimeError(f"MinerU apply url failed: {body}")
    batch_id = body["data"]["batch_id"]
    upload_url = body["data"]["file_urls"][0]
    return batch_id, upload_url


async def _upload_file(
    client: httpx.AsyncClient, upload_url: str, content: bytes
) -> None:
    """Step 2 (cont): PUT the file to MinerU's storage."""
    # MinerU requires no Content-Type header on this PUT.
    resp = await client.put(
        upload_url,
        content=content,
        timeout=300,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"MinerU upload failed: {resp.status_code} {resp.text[:200]}")


async def _poll_batch(
    client: httpx.AsyncClient,
    batch_id: str,
    *,
    max_wait: int = 300,
    interval: float = 3.0,
) -> list[dict[str, Any]]:
    """Step 3: poll batch status until each entry is done/failed (or timeout)."""
    deadline = max_wait
    elapsed = 0.0
    while elapsed < deadline:
        resp = await client.get(
            f"{BASE}/extract-results/batch/{batch_id}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") not in (0, 200):
            raise RuntimeError(f"MinerU poll failed: {body}")
        results: list[dict[str, Any]] = body.get("data", {}).get("extract_result", [])
        if not results:
            # System might not have picked up the upload yet — wait.
            await asyncio.sleep(interval)
            elapsed += interval
            continue
        states = {r.get("state") for r in results}
        if states <= {"done", "failed"}:
            return results
        await asyncio.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"MinerU batch {batch_id} timed out after {max_wait}s")


async def _download_markdown(
    client: httpx.AsyncClient, zip_url: str
) -> str:
    """Step 4: download the zip and read full.md."""
    resp = await client.get(zip_url, timeout=120, follow_redirects=True)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        md_name = next(
            (n for n in zf.namelist() if n.endswith("full.md")),
            None,
        )
        if not md_name:
            raise RuntimeError(
                f"full.md not found in zip; members: {zf.namelist()[:6]}..."
            )
        return zf.read(md_name).decode("utf-8", errors="replace")


async def parse_pdf(
    filename: str,
    content: bytes,
    *,
    max_wait: int = 300,
) -> str:
    """Top-level helper: bytes in, Markdown out. Raises on any failure."""
    data_id = f"botgroup-{filename}"
    async with httpx.AsyncClient() as client:
        batch_id, upload_url = await _request_upload_url(client, filename, data_id)
        await _upload_file(client, upload_url, content)
        results = await _poll_batch(client, batch_id, max_wait=max_wait)
        first = results[0]
        if first.get("state") == "failed":
            raise RuntimeError(
                f"MinerU parse failed: {first.get('err_msg') or 'unknown error'}"
            )
        zip_url = first.get("full_zip_url")
        if not zip_url:
            raise RuntimeError("MinerU returned no full_zip_url")
        return await _download_markdown(client, zip_url)


async def parse_pdf_with_chunks(
    filename: str,
    content: bytes,
    *,
    max_wait: int = 300,
    min_text_len: int = 16,
) -> tuple[str, list[MinedChunk]]:
    """Bytes in, (markdown, chunks_with_bbox) out.

    The zip MinerU returns contains both `full.md` (the markdown body
    used for context) and `layout.json` (a per-page tree of blocks with
    bbox coordinates). We use the latter to populate `kb_chunks.bbox_json`
    so the chat UI can highlight the cited text on the original PDF.

    `min_text_len` filters out blocks that are pure whitespace or
    single-character headers — they blow up embedding similarity without
    adding useful signal.
    """
    data_id = f"botgroup-{filename}"
    async with httpx.AsyncClient() as client:
        batch_id, upload_url = await _request_upload_url(client, filename, data_id)
        await _upload_file(client, upload_url, content)
        results = await _poll_batch(client, batch_id, max_wait=max_wait)
        first = results[0]
        if first.get("state") == "failed":
            raise RuntimeError(
                f"MinerU parse failed: {first.get('err_msg') or 'unknown error'}"
            )
        zip_url = first.get("full_zip_url")
        if not zip_url:
            raise RuntimeError("MinerU returned no full_zip_url")
        # Pull both artifacts in one round-trip — saves a full zip
        # download + unzip vs. calling _download_markdown separately.
        resp = await client.get(zip_url, timeout=180, follow_redirects=True)
        resp.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(resp.content))

        md_name = next((n for n in zf.namelist() if n.endswith("full.md")), None)
        if not md_name:
            raise RuntimeError(
                f"full.md not found in zip; members: {zf.namelist()[:6]}..."
            )
        md = zf.read(md_name).decode("utf-8", errors="replace")

        chunks: list[MinedChunk] = []
        layout_name = next((n for n in zf.namelist() if n.endswith("layout.json")), None)
        if layout_name:
            try:
                layout = json.loads(zf.read(layout_name).decode("utf-8", errors="replace"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("MinerU layout.json parse failed: %s", exc)
                layout = None
            chunks = _layout_to_chunks(layout or {}, min_text_len=min_text_len)
        else:
            # Fall back: no layout.json (older MinerU). We can't get
            # bbox but we still return the markdown so the user sees
            # *something*. The frontend will just lack highlights.
            logger.warning(
                "MinerU zip missing layout.json; bbox highlights disabled for %s",
                filename,
            )
        return md, chunks


def _layout_to_chunks(
    layout: dict[str, Any], *, min_text_len: int = 16
) -> list[MinedChunk]:
    """Walk MinerU's layout tree and yield text-bearing blocks with bbox.

    MinerU's `layout.json` carries the recognized reading order under
    `pdf_info[*].para_blocks` (3.4.x) or `preproc_blocks` (older), with
    nested `lines[*].spans[*].content` for the actual text. We collapse
    the spans into a single text body per block and keep the bbox in PDF
    user-space coordinates so pdf.js can render the highlight without
    any extra scaling. Pure-whitespace / single-character blocks are
    dropped to keep the chunk list tight.

    Older MinerU (pre-3.x) used `pages[*].blocks` with `lines` only —
    we still accept that shape for backwards compatibility.
    """
    chunks: list[MinedChunk] = []
    pages = layout.get("pdf_info") or layout.get("pages") or []
    if isinstance(pages, dict):
        pages = [pages]
    for page_idx, page in enumerate(pages, start=1):
        # MinerU 3.4.x: paragraph reading order. 3.x-pre: preproc_blocks.
        # Pre-3.x: legacy `blocks` / `layout_blocks` flat list.
        blocks = (
            page.get("para_blocks")
            or page.get("preproc_blocks")
            or page.get("blocks")
            or page.get("layout_blocks")
            or []
        )
        for block_idx, block in enumerate(blocks):
            bbox = block.get("bbox") or []
            if not bbox or len(bbox) != 4:
                continue
            lines = (
                block.get("lines")
                or block.get("segments")
                or block.get("spans")
                or []
            )
            text_pieces: list[str] = []
            for ln in lines:
                # 3.4.x: line -> spans[*].content
                if isinstance(ln, dict):
                    sub = ln.get("spans") or []
                    if sub:
                        for sp in sub:
                            if isinstance(sp, dict):
                                t = sp.get("content") or sp.get("text") or ""
                                if t:
                                    text_pieces.append(t)
                        continue
                    # Fallback: line itself carries the text
                    t = ln.get("content") or ln.get("text") or ""
                    if t:
                        text_pieces.append(t)
                else:
                    text_pieces.append(str(ln))
            text = " ".join(p.strip() for p in text_pieces if p.strip())
            if len(text) < min_text_len:
                continue
            chunks.append(
                MinedChunk(
                    block_id=block_idx,
                    page=page_idx,
                    text=text,
                    bbox=[float(b) for b in bbox],
                )
            )
    return chunks