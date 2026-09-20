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

    # ─────────────────────── RAG / 知识库 ───────────────────────
    # We dropped the RAGFlow-backed retrieval path (the engine needs
    # ≥4C8G and a Linux host with vm.max_map_count≥262144 — too heavy
    # for small dev / edge installs). The local-vector path uses
    # Postgres + pgvector for storage and the 智谱 GLM PaaS for both
    # embedding and optional rerank.
    rag_enabled: bool = True
    # Number of chunks to retrieve per bot turn before rerank.
    ragflow_top_k: int = 12
    # Number of chunks kept after the (now removed) rerank layer →
    # injected into the prompt. Hybrid (dense + BM25 + RRF) ordering
    # already promotes exact-term hits, so a small top_n is enough.
    ragflow_top_n_after_rerank: int = 5
    # Cosine-similarity threshold (0-1). Hits below this are dropped
    # before rerank. Higher = fewer but more relevant chunks.
    ragflow_score_threshold: float = 0.30

    # 智谱 GLM embedding + rerank. Same endpoint base as their PaaS API.
    zhipuai_api_key: str = ""
    zhipuai_base_url: str = "https://open.bigmodel.cn/api/paas"
    # embedding-3 (latest) or embedding-2 (legacy). Defaults to embedding-3.
    zhipuai_embedding_model: str = "embedding-3"
    # Vector dimensionality baked into the kb_chunks.embedding column.
    # GLM `embedding-3` returns 2048-dim vectors. pgvector's ANN indexes
    # (HNSW / IVFFlat) cap at 2000-dim — we run without an index for now
    # and rely on the small chunk count (a few hundred). When the
    # dataset grows past ~10k chunks we'll either downgrade the model
    # or pre-truncate to 1536 dims before storage.
    zhipuai_embedding_dim: int = 2048
    # Rerank endpoint — "rerank" set to the model id on RAG/Paas.
    zhipuai_rerank_model: str = "rerank"
    # When False, skip rerank and use the hybrid (dense + BM25 + RRF)
    # ordering directly. Useful during dev when GLM rerank quota is
    # exhausted; also the default now since the rerank layer was
    # observed to drop exact-term hits (e.g. "Referral to SPC / Treaty")
    # in favour of semantically-similar chunks.
    zhipuai_rerank_enabled: bool = False

    # ─── Hybrid retrieval (BM25 + dense + RRF) ───
    # When True, run a parallel full-text-search leg via Postgres
    # `tsvector @@ tsquery` and fuse the ranked lists with Reciprocal
    # Rank Fusion. Setting False degrades to the legacy dense-only
    # path (used as a kill switch when something goes wrong).
    rag_hybrid_enabled: bool = True
    # Per-leg candidate cap. Picked conservatively so the rerank step
    # still has a meaningful top-N to chew on.
    rag_top_k_dense: int = 50
    rag_top_k_bm25: int = 50
    # RRF smoothing constant. 60 is the Cormack-et-al default; tune via
    # A/B if precision@5 starts dropping on a curated eval set.
    rag_rrf_k: int = 60
    # Sentence-window: how many neighbouring blocks (by `para`) to
    # stitch around each retrieval hit before injecting into the LLM
    # prompt. 0 disables the feature (legacy behaviour). 1 means the
    # LLM sees the previous block + the hit + the next block on the
    # same page — enough context for short legal/insurance clauses
    # without bloating the prompt. Larger values give the model more
    # surrounding text at the cost of tokens.
    rag_window_size: int = 1

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