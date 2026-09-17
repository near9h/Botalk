"""FastAPI entrypoint."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import ensure_bootstrap_user
from app.config import get_settings
from app.api import auth as auth_api
from app.api import bots, groups, messages, chat, models, attachments, skills, runs, tasks
from app.db.session import SessionLocal
from app.skills.registry import ensure_builtin_skills

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed the bootstrap user (no-op once any user exists) and upsert the
    # built-in skills (idempotent by key) so the skill center is never empty.
    async with SessionLocal() as session:
        await ensure_bootstrap_user(session)
        await ensure_builtin_skills(session)
    yield


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
app.include_router(bots.router, prefix="/api/bots", tags=["bots"])
app.include_router(groups.router, prefix="/api/groups", tags=["groups"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(attachments.router, prefix="/api/attachments", tags=["attachments"])
app.include_router(skills.router, prefix="/api/skills", tags=["skills"])