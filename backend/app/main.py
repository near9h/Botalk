"""FastAPI entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.auth import ensure_bootstrap_user
from app.config import get_settings
from app.api import auth as auth_api
from app.api import bots, groups, messages, chat, models, attachments, skills, runs, tasks
from app.api import users as users_api
from app.api import audit as audit_api
from app.api import kb as kb_api
from app.api import policies as policies_api
from app.db.session import SessionLocal
from app.services import audit as audit_service
from app.services import ragflow_client
from app.skills.registry import ensure_builtin_skills
from app.workers import ingest_worker

settings = get_settings()
log = logging.getLogger("botgroup.audit")


def _check_env_file_permissions() -> None:
    """Fix for security audit item A4.

    The .env file ships with API keys + AUTH_SECRET in plaintext. On
    a shared host any local user can read it (default 0644). We log
    a loud warning at boot when the file is group/world readable so
    the operator notices; we don't refuse to start because dev
    environments often run with looser permissions and we don't want
    to brick them on every code change.
    """
    env_path = Path(".env")
    if not env_path.exists():
        return
    mode = env_path.stat().st_mode & 0o777
    leaky_bits = mode & 0o077  # group|other read/write/execute
    if leaky_bits:
        log.warning(
            "SECURITY: .env is world/group readable (mode=%s). "
            "Run `chmod 600 .env` to protect the API keys it contains.",
            oct(mode),
        )


_check_env_file_permissions()


# SlowAPI rate limiter. `key_func` uses the proxy-injected X-Real-IP
# when present (which nginx sets to the actual client address via
# PROXY protocol) and falls back to the socket peer — matches the
# `client_ip()` logic in `app/services/audit.py` so the rate limit
# key and the audit log use the same source of truth.
def _real_client_ip(request: Request) -> str:
    return (
        request.headers.get("x-real-ip")
        or (request.client.host if request.client else "")
        or "unknown"
    )


limiter = Limiter(
    key_func=_real_client_ip,
    default_limits=["200/minute"],
    headers_enabled=True,
)

# The auth router picks the limiter up via `request.app.state.limiter`
# at request time (see `app/api/auth.py`). Module-load late binding
# is no longer needed — `limiter` is only attached to the app below.


async def _audit_cleanup_loop() -> None:
    """每天 0 点清理一次过期 audit log；retention=0 时跳过。"""
    if settings.audit_retention_days <= 0:
        return
    while True:
        try:
            now = datetime.now(tz=timezone.utc)
            # 下一次 0 点
            target = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target.fromtimestamp(target.timestamp() + 86400, tz=timezone.utc)
            wait = (target - now).total_seconds()
            await asyncio.sleep(wait)
            async with SessionLocal() as session:
                deleted = await audit_service.cleanup_old_logs(
                    session, retention_days=settings.audit_retention_days
                )
                log.info("audit cleanup: deleted %s rows", deleted)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("audit cleanup failed: %s", exc)
            await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed the bootstrap user (no-op once any user exists) and upsert the
    # built-in skills (idempotent by key) so the skill center is never empty.
    async with SessionLocal() as session:
        await ensure_bootstrap_user(session)
        await ensure_builtin_skills(session)
    # 启动时立即清理一次（避免长跑进程无限堆积）
    if settings.audit_retention_days > 0:
        async with SessionLocal() as session:
            try:
                deleted = await audit_service.cleanup_old_logs(
                    session, retention_days=settings.audit_retention_days
                )
                log.info("startup audit cleanup: deleted %s rows", deleted)
            except Exception as exc:  # noqa: BLE001
                log.warning("startup audit cleanup failed: %s", exc)

    # Ping RAGFlow once at boot so the operator knows the connection
    # works (or doesn't). Failure is logged but doesn't abort startup —
    # the chat orchestrator already short-circuits when RAG is down.
    if ragflow_client.is_configured():
        try:
            client = await ragflow_client.get_client()
            datasets = await client.list_datasets()
            log.info("RAGFlow reachable: %d existing dataset(s)", len(datasets))
        except Exception as exc:  # noqa: BLE001
            log.warning("RAGFlow unreachable at startup: %s", exc)

    cleanup_task = asyncio.create_task(_audit_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        # Wait for in-flight KB ingest jobs to finish (or best-effort
        # abort after a short grace window). Prevents dropping an
        # upload that already returned 201 to the user.
        try:
            await asyncio.wait_for(ingest_worker.wait_all(), timeout=15)
        except asyncio.TimeoutError:
            log.warning("KB ingest tasks didn't drain in 15s during shutdown")
        # Tear down the shared RAGFlow HTTP client.
        try:
            await ragflow_client.aclose_client()
        except Exception:  # noqa: BLE001
            pass


app = FastAPI(
    title="BotGroup API",
    version="0.1.0",
    description="Multi-bot group chat backend powered by AgentScope + NewAPI gateway.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# API routers — these imports were moved to the top of the file
# so the `auth_api._limiter_ref["v"] = limiter` line above can resolve
# at module-load time (Python only resolves names defined in scope).
# Module import order still satisfies include_router() — auth_api
# just becomes a no-op since we never reach the late-binding line
# until after all modules are loaded.


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


app.include_router(auth_api.router, prefix="/api/auth", tags=["auth"])
app.include_router(users_api.router, prefix="/api/users", tags=["users"])
app.include_router(audit_api.router, prefix="/api/audit", tags=["audit"])
app.include_router(bots.router, prefix="/api/bots", tags=["bots"])
app.include_router(groups.router, prefix="/api/groups", tags=["groups"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(attachments.router, prefix="/api/attachments", tags=["attachments"])
app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
app.include_router(kb_api.router, prefix="/api/kb", tags=["knowledge-bases"])
app.include_router(policies_api.router, prefix="/api/policies", tags=["policies"])