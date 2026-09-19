"""Thin async wrapper around the RAGFlow HTTP API.

RAGFlow is the engine backing the `路线 RAG` (knowledge base) pipeline.
We talk to it through HTTP only — no Python SDK — so this module is the
single integration point and can be mocked in tests.

Why a wrapper and not raw `httpx` calls scattered across the codebase:
  - Centralizes the API-key header and base URL handling.
  - Normalizes RAGFlow's `{code, data}` envelope into plain exceptions so
    call sites don't need to know the wire format.
  - Provides a single `is_configured()` gate so the rest of the app can
    gracefully fall back to the no-KB path when RAGFlow isn't deployed.

Endpoints we hit (v0.27+ API):
  GET    /api/v1/datasets                   — list datasets
  POST   /api/v1/datasets                   — create dataset
  DELETE /api/v1/datasets/{id}              — drop a dataset
  POST   /api/v1/datasets/{id}/documents    — upload a file (multipart)
  GET    /api/v1/datasets/{id}/documents    — list documents in a dataset
  DELETE /api/v1/datasets/{id}/documents/{doc_id} — drop a doc
  POST   /api/v1/chunk/retrieve             — semantic retrieval (used at chat time)
  GET    /api/v1/datasets/{id}/chunks       — list chunks of a doc (post-ingest)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────── helpers ───────────────────────────


def _base() -> str:
    """RAGFlow base URL with trailing slash stripped.

    Accepts either `http://ragflow:9380` or `http://ragflow:9380/api/v1`.
    """
    url = (settings.ragflow_base_url or "").rstrip("/")
    if not url:
        return ""
    # Strip the `/api/v1` suffix if the operator pasted the v1 root into
    # the env var — we re-add it per-endpoint.
    if url.endswith("/api/v1"):
        url = url[: -len("/api/v1")]
    return url


def is_configured() -> bool:
    """True iff RAGFlow is enabled AND has a base URL.

    The chat orchestrator uses this to skip the retrieval step entirely
    when RAG isn't deployed (dev environment without enough RAM for the
    RAGFlow stack).
    """
    return bool(settings.rag_enabled and settings.ragflow_base_url)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.ragflow_api_key}",
        "Content-Type": "application/json",
    }


class RAGFlowError(RuntimeError):
    """Raised when RAGFlow returns a non-zero `code` or an HTTP error.

    The original response body is attached as `.body` for debugging.
    """

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: Any = None,
    params: Any = None,
    files: Any = None,
    timeout: float = 60.0,
) -> Any:
    """Send one request and unwrap the RAGFlow `{code, data}` envelope.

    Raises `RAGFlowError` if RAGFlow returns code != 0 or a non-2xx HTTP
    status. The original response body is attached to the exception.
    """
    url = f"{_base()}/api/v1{path}"
    headers = _headers()
    # Multipart upload sets its own Content-Type with a boundary.
    if files is not None:
        headers.pop("Content-Type", None)
    resp = await client.request(
        method,
        url,
        headers=headers,
        json=json,
        params=params,
        files=files,
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RAGFlowError(
            f"RAGFlow HTTP {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
            body=resp.text,
        )
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    code = body.get("code") if isinstance(body, dict) else None
    # RAGFlow uses code 0 for success; some endpoints return 200 directly.
    if code is not None and code not in (0, 200):
        raise RAGFlowError(
            f"RAGFlow code={code}: {body.get('message') or body}",
            body=body,
        )
    return body.get("data") if isinstance(body, dict) else body


# ─────────────────────────── client ───────────────────────────


class RAGFlowClient:
    """Stateful RAGFlow wrapper. One instance per request, or share via
    `_shared_client()`. The constructor doesn't validate connectivity;
    errors surface lazily on the first call.
    """

    def __init__(self, *, timeout: float = 60.0):
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "RAGFlowClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ── datasets ──

    async def list_datasets(self) -> list[dict[str, Any]]:
        return await _request(self._client, "GET", "/datasets")

    async def create_dataset(
        self, name: str, *, description: str = ""
    ) -> str:
        """Create a new dataset. Returns the engine-side `id` string."""
        data = await _request(
            self._client,
            "POST",
            "/datasets",
            json={
                "name": name,
                "description": description,
                # We pre-chunk via MinerU + GLM embedding; disable RAGFlow's
                # built-in DeepDoc OCR / Naive chunker. Rerank also goes
                # through our own GLM rerank call, not RAGFlow's built-in
                # rerank.
                "parser_config": {
                    "chunk_method": "naive",
                    "delimiter": "\n",
                },
                "embedding_config": {
                    "provider": "zhipuai",
                    "model": settings.zhipuai_embedding_model,
                },
                "rerank_config": {
                    "provider": "zhipuai",
                    "model": settings.zhipuai_rerank_model,
                },
            },
            timeout=30,
        )
        return str(data["id"])

    async def delete_dataset(self, dataset_id: str) -> None:
        await _request(
            self._client, "DELETE", f"/datasets/{dataset_id}", timeout=30,
        )

    # ── documents ──

    async def upload_document(
        self,
        dataset_id: str,
        *,
        filename: str,
        content: bytes,
        mime_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file to a dataset. Returns the engine-side doc id.

        RAGFlow's upload endpoint expects `multipart/form-data` with a
        single `file` part. We pass the raw bytes from `content_md` /
        `storage_path` so the chat-side upload pipeline and the KB
        ingest pipeline share the same code path.
        """
        data = await _request(
            self._client,
            "POST",
            f"/datasets/{dataset_id}/documents",
            files={"file": (filename, content, mime_type)},
            timeout=120,
        )
        # RAGFlow v0.27 returns `[{id, name}]` (a list) when uploading
        # one file at a time. Older versions return `{id, name}`. Handle
        # both so we don't break on either.
        if isinstance(data, list):
            return str(data[0]["id"])
        return str(data["id"])

    async def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        data = await _request(
            self._client, "GET", f"/datasets/{dataset_id}/documents",
        )
        # Always returns a list in v0.27.
        return data if isinstance(data, list) else data.get("docs", [])

    async def list_chunks(
        self, dataset_id: str, doc_id: str
    ) -> list[dict[str, Any]]:
        data = await _request(
            self._client, "GET", f"/datasets/{dataset_id}/documents/{doc_id}/chunks",
        )
        return data.get("chunks", []) if isinstance(data, dict) else data

    async def delete_document(self, dataset_id: str, doc_id: str) -> None:
        await _request(
            self._client,
            "DELETE",
            f"/datasets/{dataset_id}/documents/{doc_id}",
            timeout=30,
        )

    # ── retrieval ──

    async def retrieval(
        self,
        dataset_id: str,
        question: str,
        *,
        top_k: int = 12,
    ) -> list[dict[str, Any]]:
        """Semantic + keyword retrieval over a dataset.

        Returns a list of chunks, each shaped like:
          {
            "id": "...",
            "content": "...text body...",
            "document_id": "...",
            "document_name": "filename.pdf",
            "dataset_id": "...",
            "score": 0.87,
            "positions": [
              # only on PDF docs:
              [{"page": 3, "rect": [x1, y1, x2, y2]}, ...]
            ],
          }

        Note: RAGFlow's `positions` payload is the engine's view of where
        the chunk's text sits inside the original PDF. We pass these
        through unchanged to the chat UI so pdf.js can overlay the bbox.
        """
        data = await _request(
            self._client,
            "POST",
            "/chunk/retrieve",
            json={
                "dataset_ids": [dataset_id],
                "question": question,
                "top_k": top_k,
                # page similarity = -1 means "use RAGFlow default ranking"
                "similarity_threshold": settings.ragflow_score_threshold,
                "vector_similarity_weight": 0.5,
                # RAGFlow does its own keyword+vector blend; we leave the
                # defaults here so the engine tunes them for us.
                "highlight": True,
                "cross_languages": ["zh", "en"],
            },
            timeout=30,
        )
        # v0.27 wraps chunks inside `data["chunks"]`. Older versions
        # return a flat list. Handle both.
        if isinstance(data, dict):
            return data.get("chunks", []) or data.get("records", [])
        return data if isinstance(data, list) else []


# ─────────────────────────── singleton ───────────────────────────


_client: RAGFlowClient | None = None
_client_lock = asyncio.Lock()


async def get_client() -> RAGFlowClient:
    """Module-level singleton so we don't pay the TLS handshake per call.

    Use this from chat / KB services. Tests should `await get_client().aclose()`
    in their teardown.
    """
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = RAGFlowClient()
    return _client


async def aclose_client() -> None:
    """Cleanly close the singleton on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None