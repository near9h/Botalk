"""MinerU PDF parser integration.

Flow (batch-mode, server-side upload):
  1. POST /api/v4/file-urls/batch  → {batch_id, file_urls[]}
  2. PUT  file_urls[0]  (the PDF bytes)
  3. GET  /api/v4/extract-results/batch/{batch_id}  → polls until
     per-file state is `done` or `failed`. Each entry has `full_zip_url`.
  4. Download the zip, unzip, read `full.md`.
"""
from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE = "https://mineru.net/api/v4"


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