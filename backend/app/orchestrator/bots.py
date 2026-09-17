"""Bot → OpenAI-compatible chat client.

We talk directly to NewAPI via the official `openai` SDK in OpenAI-compatible mode.
This avoids pulling in AgentScope (heavy, slow PyPI install) and keeps the
codebase trivially auditable: one HTTP client, one streaming call.
"""
from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import get_settings
from app.db.models import Bot

settings = get_settings()


@lru_cache(maxsize=1)
def _shared_client() -> AsyncOpenAI:
    """One shared AsyncOpenAI client pointed at the NewAPI gateway."""
    return AsyncOpenAI(
        api_key=settings.newapi_api_key,
        base_url=settings.newapi_base_url,
        timeout=settings.request_timeout_seconds,
        max_retries=2,
    )


def client_for(_bot: Bot) -> AsyncOpenAI:
    """Return the shared client (per-bot overrides can layer in later)."""
    return _shared_client()