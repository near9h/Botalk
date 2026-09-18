"""FastAPI entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import ensure_bootstrap_user
from app.config import get_settings
from app.api import auth as auth_api
from app.api import bots, groups, messages, chat, models, attachments, skills, runs, tasks
from app.api import users as users_api
from app.api import audit as audit_api
from app.db.session import SessionLocal
from app.services import audit as audit_service
from app.skills.registry import ensure_builtin_skills

settings = get_settings()
log = logging.getLogger("botgroup.audit")


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

    cleanup_task = asyncio.create_task(_audit_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
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