"""Audit log service.

提供：
- `AuditContext`：从 Request 抽 ip / ua / actor
- `audit_ctx(request, user)`：FastAPI 依赖
- `log(...)`：fire-and-forget 写一条 audit log（失败不抛）
- `cleanup_old_logs(session, retention_days)`：返回删除条数

按 .trae/documents/user-mgmt-audit-log-plan.md 设计。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db.models import AuditLog, User


@dataclass
class AuditContext:
    """由 `audit_ctx` 依赖从 Request + User 一次性构造；路由处理函数直接复用。"""
    actor: User | None
    ip: str
    user_agent: str

    def safe_actor(self) -> tuple[int | None, str, str]:
        """返回 (id, name, role)；匿名时给空字符串。"""
        if self.actor is None:
            return None, "", "anonymous"
        return self.actor.id, self.actor.username, self.actor.role


async def audit_ctx(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user)] = None,
) -> AuditContext:
    """FastAPI 依赖：路由只需 `ctx: AuditContext = Depends(audit_ctx)`。

    注意：匿名路由（auth.login 等）也用这个依赖；user 为 None 时
    safe_actor() 仍然能给出 (None, '', 'anonymous')。
    """
    ip = client_ip(request)
    ua = request.headers.get("user-agent", "")[:500]
    return AuditContext(actor=user, ip=ip, user_agent=ua)


def client_ip(request: Request) -> str:
    """取真实客户端 IP。

    请求都经由 nginx 反代，`request.client.host` 拿到的是反代容器的
    内网地址（如 172.19.0.5），不是访客 IP。nginx 侧已用 PROXY
    protocol + real_ip 模块把 `$remote_addr` 还原成真实客户端，因此
    它注入的这两个头可信：

    - `X-Real-IP`：nginx 无条件覆盖为 `$remote_addr`，客户端伪造无效；
    - `X-Forwarded-For`：`$proxy_add_x_forwarded_for` 会保留客户端自带
      的值再追加一跳，所以只有**最右侧**那一跳可信。

    直连（未过反代，如本地脚本）时两个头都没有，回退到 TCP 对端。
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else ""


async def log(
    session: AsyncSession,
    ctx: AuditContext,
    *,
    action: str,
    target_type: str,
    target_id: str | None = None,
    target_name: str | None = None,
    status: str = "success",
    detail: dict[str, Any] | None = None,
) -> None:
    """写一条审计日志。失败时打 stderr 但不抛（不阻断主业务）。"""
    try:
        actor_id, actor_name, actor_role = ctx.safe_actor()
        entry = AuditLog(
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            ip=ctx.ip or None,
            user_agent=ctx.user_agent or None,
            status=status,
            detail=detail or {},
        )
        session.add(entry)
        await session.flush()
    except Exception as exc:  # noqa: BLE001
        # 不抛：审计失败不能让用户丢数据
        import sys
        print(f"[audit] failed to write {action}: {exc}", file=sys.stderr)


async def cleanup_old_logs(
    session: AsyncSession, *, retention_days: int = 90
) -> int:
    """删除 occurred_at < now() - retention_days 的全部日志；返回条数。"""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(
        delete(AuditLog).where(AuditLog.occurred_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)


async def list_logs(
    session: AsyncSession,
    *,
    actor_id: int | None = None,
    actor_role: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    ip: str | None = None,
    occurred_from: Any = None,
    occurred_to: Any = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    """按多维筛选 + 分页。返回 (rows, total_count)。"""
    from sqlalchemy import func as sa_func

    q = select(AuditLog)
    count_q = select(sa_func.count(AuditLog.id))
    for col, val in (
        (AuditLog.actor_id, actor_id),
        (AuditLog.action, action),
        (AuditLog.target_type, target_type),
        (AuditLog.target_id, target_id),
        (AuditLog.actor_role, actor_role),
        (AuditLog.status, status),
    ):
        if val is not None:
            q = q.where(col == val)
            count_q = count_q.where(col == val)
    # IP 模糊匹配：用户只输入一段也能命中（如 172.19 / 172.19.0.5）
    if ip:
        like = f"%{ip.strip()}%"
        q = q.where(AuditLog.ip.ilike(like))
        count_q = count_q.where(AuditLog.ip.ilike(like))
    if occurred_from is not None:
        q = q.where(AuditLog.occurred_at >= occurred_from)
        count_q = count_q.where(AuditLog.occurred_at >= occurred_from)
    if occurred_to is not None:
        q = q.where(AuditLog.occurred_at <= occurred_to)
        count_q = count_q.where(AuditLog.occurred_at <= occurred_to)

    total = (await session.execute(count_q)).scalar_one() or 0
    q = q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(q)).scalars().all())
    return rows, int(total)


async def stats_last_24h(session: AsyncSession) -> dict[str, Any]:
    """返回最近 24h 的 action 计数 + top-10 actor。给 /api/audit/stats 用。"""
    from sqlalchemy import func as sa_func
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)

    by_action = (
        await session.execute(
            select(AuditLog.action, sa_func.count(AuditLog.id))
            .where(AuditLog.occurred_at >= cutoff)
            .group_by(AuditLog.action)
            .order_by(sa_func.count(AuditLog.id).desc())
            .limit(20)
        )
    ).all()

    by_actor = (
        await session.execute(
            select(AuditLog.actor_name, sa_func.count(AuditLog.id))
            .where(AuditLog.occurred_at >= cutoff)
            .where(AuditLog.actor_id.is_not(None))
            .group_by(AuditLog.actor_name)
            .order_by(sa_func.count(AuditLog.id).desc())
            .limit(10)
        )
    ).all()

    total = (
        await session.execute(
            select(sa_func.count(AuditLog.id)).where(AuditLog.occurred_at >= cutoff)
        )
    ).scalar_one() or 0

    return {
        "total_last_24h": int(total),
        "by_action": [{"action": a, "count": int(c)} for a, c in by_action],
        "by_actor": [{"actor": n, "count": int(c)} for n, c in by_actor],
    }