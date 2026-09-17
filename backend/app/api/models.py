"""Model catalog + per-model health probe.

Proxies NewAPI's `GET /v1/models` so the frontend can populate a model picker
without hard-coding model IDs. Includes a tiny in-memory cache (60 s) to avoid
hammering NewAPI on every bot-form open.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter()
settings = get_settings()

_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL_SECONDS = 60.0
_LOCK = asyncio.Lock()


class TestRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(default="用一句话介绍你自己", max_length=2000)
    temperature: float = Field(default=0.5, ge=0, le=2)


class TestResponse(BaseModel):
    ok: bool
    model: str
    reply: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None


async def _fetch_models() -> dict[str, Any]:
    url = f"{settings.newapi_base_url.rstrip('/')}/models"
    headers = {
        "Authorization": f"Bearer {settings.newapi_api_key}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"NewAPI /models returned {resp.status_code}: {resp.text[:200]}",
        )
    return resp.json()


def _enrich(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach a derived `vendor` field for nicer grouping in the UI."""
    out = []
    for m in payload.get("data", []):
        model_id = m.get("id", "")
        owned_by = m.get("owned_by", "")
        vendor = _classify(model_id, owned_by)
        out.append(
            {
                "id": model_id,
                "owned_by": owned_by,
                "vendor": vendor,
            }
        )
    # Stable order: vendor alphabetical, then id alphabetical.
    out.sort(key=lambda x: (x["vendor"], x["id"]))
    return out


def _classify(model_id: str, owned_by: str) -> str:
    mid = model_id.lower()
    oid = owned_by.lower()
    if "gpt" in mid or "openai" in oid or "o1" in mid or "o3" in mid or "o4" in mid:
        return "openai"
    if "claude" in mid or "anthropic" in oid:
        return "anthropic"
    if "gemini" in mid or "google" in oid or "palm" in mid:
        return "google"
    if "gpt" in mid and "agnes" in mid:
        return "openai"
    if "agnes" in mid:
        return "openai"
    if "zhipu" in mid or "glm" in mid or "chatglm" in mid:
        return "zhipu"
    if "qwen" in mid or "dashscope" in oid or "tongyi" in mid:
        return "alibaba"
    if "deepseek" in mid:
        return "deepseek"
    if "doubao" in mid or "volcengine" in oid:
        return "bytedance"
    if "kimi" in mid or "moonshot" in mid:
        return "moonshot"
    if "wenxin" in mid or "ernie" in mid:
        return "baidu"
    if "minimax" in oid:
        return "minimax"
    return "other"


@router.get("")
async def list_models() -> dict[str, Any]:
    now = time.time()
    if _CACHE["data"] is not None and (now - _CACHE["ts"]) < _CACHE_TTL_SECONDS:
        return {"data": _CACHE["data"], "cached": True}

    async with _LOCK:
        # Re-check inside the lock to avoid duplicate upstream calls.
        if _CACHE["data"] is not None and (time.time() - _CACHE["ts"]) < _CACHE_TTL_SECONDS:
            return {"data": _CACHE["data"], "cached": True}
        payload = await _fetch_models()
        enriched = _enrich(payload)
        _CACHE["data"] = enriched
        _CACHE["ts"] = time.time()
        return {"data": enriched, "cached": False}


@router.post("/test", response_model=TestResponse)
async def test_model(body: TestRequest) -> TestResponse:
    """Send a small probe request to the chosen model and report the outcome.

    This hits NewAPI with a tiny prompt and reports back: reply text, latency,
    token usage (when the model returns it), or the raw error if it fails.
    Useful for verifying that a NewAPI channel is configured correctly before
    creating bots that depend on it.
    """
    url = f"{settings.newapi_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.newapi_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": body.model,
        "messages": [{"role": "user", "content": body.prompt}],
        "temperature": body.temperature,
        "max_tokens": 256,
        "stream": False,
    }
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        return TestResponse(
            ok=False,
            model=body.model,
            error=f"network error: {exc.__class__.__name__}: {exc}",
            latency_ms=int((time.time() - started) * 1000),
        )

    latency_ms = int((time.time() - started) * 1000)
    raw = None
    text = ""
    try:
        raw = resp.json()
    except Exception:
        raw = {"_non_json_body": resp.text[:500]}

    if resp.status_code != 200:
        # Try to extract a clean error message from the NewAPI payload.
        err_msg = None
        if isinstance(raw, dict):
            err = raw.get("error")
            if isinstance(err, dict):
                err_msg = err.get("message") or json_dumps(raw)[:300]
            elif isinstance(err, str):
                err_msg = err
        if not err_msg:
            err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
        return TestResponse(
            ok=False,
            model=body.model,
            error=err_msg,
            latency_ms=latency_ms,
            raw=raw if isinstance(raw, dict) else None,
        )

    # Parse a normal successful response.
    try:
        choices = raw.get("choices") if isinstance(raw, dict) else None
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                # Some models stream a list of {type, text} parts.
                text = "".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
        usage = raw.get("usage") if isinstance(raw, dict) else None
    except Exception as exc:  # noqa: BLE001
        return TestResponse(
            ok=False,
            model=body.model,
            error=f"response parse error: {exc}",
            latency_ms=latency_ms,
            raw=raw if isinstance(raw, dict) else None,
        )

    return TestResponse(
        ok=True,
        model=body.model,
        reply=text or "(空回复)",
        latency_ms=latency_ms,
        prompt_tokens=(usage or {}).get("prompt_tokens") if isinstance(usage, dict) else None,
        completion_tokens=(usage or {}).get("completion_tokens") if isinstance(usage, dict) else None,
        total_tokens=(usage or {}).get("total_tokens") if isinstance(usage, dict) else None,
        raw=None,
    )


def json_dumps(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)[:300]