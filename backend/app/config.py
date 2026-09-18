"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings sourced from .env / environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # NewAPI gateway (OpenAI-compatible)
    newapi_base_url: str = "https://your-newapi.example.com/v1"
    newapi_api_key: str = "sk-placeholder"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://botgroup:botgroup@postgres:5432/botgroup"

    # CORS
    cors_origins: str = "http://localhost:3500,http://localhost:3000"

    # App
    app_env: str = "development"
    default_max_rounds: int = 3
    # Model used for the post-discussion summarizer pass. Leave empty to
    # fall back to the first bot's model (which is guaranteed routable on
    # the NewAPI gateway because it just succeeded in the same run).
    orchestrator_model: str = ""
    # Safety limits for NewAPI calls (reasoning models can explode token usage)
    max_tokens_per_call: int = 2048
    request_timeout_seconds: float = 120.0

    # Skill tools — third-party API keys (optional). When empty, the built-in
    # search/crawl tools fall back to direct httpx fetching.
    tavily_api_key: str = ""
    serper_api_key: str = ""
    firecrawl_api_key: str = ""
    # MCP client timeout for connecting to / listing tools of remote servers.
    mcp_timeout_seconds: float = 30.0
    # Optional community skill-market registry URL. Empty disables the
    # `/api/skills/community/search` endpoint and hides search in the UI.
    skill_market_api_url: str = ""
    # Bearer / API key for the market. Sent either as `Authorization: Bearer`
    # or as `?api_key=` query param (driven by `skill_market_auth_style`).
    skill_market_api_key: str = ""
    # "bearer" (default) | "query" — how to attach `skill_market_api_key`.
    skill_market_auth_style: str = "bearer"

    # Optional GitHub token used for community search (find-skills,
    # anthropics/skills). Raises the unauthenticated rate limit from
    # 60→5000 req/h. Anonymous calls still work but may 429 under load.
    github_token: str = ""

    # MinerU PDF parser — used to turn uploaded PDFs into Markdown context.
    mineru_api_key: str = ""
    # MinerU model: pipeline (default) | vlm | MinerU-HTML
    mineru_model_version: str = "vlm"
    # Where uploaded files are temporarily stored on the backend host.
    upload_dir: str = "/tmp/botgroup-uploads"
    # Max accepted upload size in bytes (200MB matches MinerU's own limit).
    max_upload_bytes: int = 200 * 1024 * 1024

    # Auth — secret used to JWT-sign session cookies. Override in .env!
    auth_secret: str = "change-me-in-env-please-very-long-random-string"
    auth_token_ttl_hours: int = 24 * 7  # 1 week
    # Bootstrap credentials — only used the first time the User table is empty.
    auth_bootstrap_user: str = "admin"
    auth_bootstrap_password: str = "admin"
    # If true, /api/auth/* always works without a session. Useful for
    # local/self-hosted deployments where login isn't desired.
    auth_disabled: bool = False

    # 审计日志保留天数；超过的记录会被后台清理任务删除。设为 0 关闭清理。
    audit_retention_days: int = 90

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


_DEFAULT_SECRETS = frozenset({
    "change-me-in-env-please-very-long-random-string",
    "change-me-please-use-a-long-random-string",
})


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Fail fast on a hardcoded default JWT secret. Without this check, an
    # operator who forgets to set AUTH_SECRET would silently issue tokens
    # signed with a value published in the public source tree — anyone
    # reading the repo could forge a session cookie.
    if s.auth_secret in _DEFAULT_SECRETS and not s.auth_disabled:
        raise RuntimeError(
            "AUTH_SECRET is still set to the public default. "
            "Override it in .env (or via the env var AUTH_SECRET). "
            "To bypass auth entirely for local dev, set AUTH_DISABLED=true."
        )
    return s