"""审计日志查询 API — admin-only。"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query as FQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.config import get_settings
from app.db.models import User
from app.db.session import get_session
from app.schemas import AuditCleanupResult, AuditLogOut, AuditLogsPage
from app.services import audit as audit_service

router = APIRouter()
settings = get_settings()


@router.get("/logs", response_model=AuditLogsPage)
async def list_logs(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
    actor_id: int | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = FQuery(50, ge=1, le=500),
    offset: int = FQuery(0, ge=0),
) -> AuditLogsPage:
    rows, total = await audit_service.list_logs(
        session,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )
    return AuditLogsPage(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/logs/{log_id}", response_model=AuditLogOut)
async def get_log(
    log_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AuditLogOut:
    from app.db.models import AuditLog
    from sqlalchemy import select

    row = (
        await session.execute(select(AuditLog).where(AuditLog.id == log_id))
    ).scalar_one_or_none()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="log not found")
    return AuditLogOut.model_validate(row)


@router.get("/stats")
async def stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> dict:
    return await audit_service.stats_last_24h(session)


@router.post("/cleanup", response_model=AuditCleanupResult)
async def cleanup(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AuditCleanupResult:
    deleted = await audit_service.cleanup_old_logs(
        session, retention_days=settings.audit_retention_days
    )
    return AuditCleanupResult(
        deleted=deleted, retention_days=settings.audit_retention_days
    )