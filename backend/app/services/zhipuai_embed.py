"""智谱 GLM embedding + rerank (Paas API).

RAGFlow is configured to delegate embedding to this same endpoint
(`provider=zhipuai, model=embedding-3` in `ragflow_client.create_dataset`).
This module mirrors that capability on the BotGroup side so we can:

  1. Re-rank the `top_k` chunks RAGFlow returns with `zhipuai rerank`
     before injecting them into the LLM prompt — RAGFlow's built-in
     reranker is fine but GLM's reranker consistently scores higher on
     Chinese benchmarks and is what the rest of the project already
     uses for LLM calls.

  2. Pre-compute embeddings for a small KB doc preview (when the user
     opens "检索测试" and we want to show "what would this query
     retrieve?" *before* committing to the real chunk set).

Both endpoints follow the same auth pattern (`Authorization: Bearer`).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def is_configured() -> bool:
    return bool(settings.zhipuai_api_key)


def _url(path: str) -> str:
    base = settings.zhipuai_base_url.rstrip("/")
    return f"{base}{path}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.zhipuai_api_key}",
        "Content-Type": "application/json",
    }


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Compute dense vectors for a list of strings.

    Returns one vector per input. The model's dimensionality is implicit
    in the response — RAGFlow/GLM `embedding-3` returns 1024-dim, but we
    don't depend on that here (we only use embed_texts internally).

    Batches are limited to 64 texts per request to stay under the
    default 8 MB payload limit and to keep latency predictable.
    """
    if not texts:
        return []
    if not is_configured():
        raise RuntimeError("ZHIPUAI_API_KEY not configured")

    all_vecs: list[list[float]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            resp = await client.post(
                _url("/v4/embeddings"),
                headers=_headers(),
                json={
                    "model": settings.zhipuai_embedding_model,
                    "input": batch,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            # GLM returns: {"data": [{"embedding": [...], "index": 0}, ...]}
            for item in payload.get("data", []):
                all_vecs.append(item["embedding"])
    return all_vecs


async def rerank(
    query: str,
    documents: list[str],
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Re-rank `documents` against `query` using GLM rerank.

    Returns a list of `{index, score, document}` dicts ordered by
    relevance (highest score first). When `top_n` is set, only the top N
    entries are returned.

    GLM PaaS endpoint: POST /v4/rerank  body {query, documents, top_n,
    return_documents, model}. Response: `{results: [...], usage}`.

    The model id is taken from `settings.zhipuai_rerank_model` — for the
    PaaS endpoint this is typically just "rerank".
    """
    if not documents:
        return []
    if not is_configured():
        raise RuntimeError("ZHIPUAI_API_KEY not configured")
    if top_n is None:
        top_n = len(documents)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _url("/v4/rerank"),
            headers=_headers(),
            json={
                "model": settings.zhipuai_rerank_model,
                "query": query,
                "documents": documents,
                "top_n": min(top_n, len(documents)),
                "return_documents": False,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    results = payload.get("results", [])
    # GLM returns `{index, relevance_score}`. We surface the snippet back
    # so the chat orchestrator can build the prompt without re-mapping.
    out: list[dict[str, Any]] = []
    for r in results:
        idx = int(r["index"])
        out.append(
            {
                "index": idx,
                "score": float(r["relevance_score"]),
                "document": documents[idx] if 0 <= idx < len(documents) else "",
            }
        )
    return out