"""平台群规 / 防火墙规则 接口。

- `GET /api/policies`  ：任何登录用户可读（供群详情页展示「平台群规」横幅）
- `PUT /api/policies`  ：仅管理员可写，整表替换单行 `system_policies`

`preview` 字段由 `app.services.policy` 的同一套渲染逻辑算出，
保证管理页看到的内容与真正注入 system prompt 的内容完全一致。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin, require_user
from app.db.models import SystemPolicy, User
from app.db.session import get_session
from app.schemas import PolicyOut, PolicyRule, PolicyUpdate
from app.services import audit as audit_service
from app.services.policy import (
    MAX_PLATFORM_BLOCK,
    POLICY_ROW_ID,
    load_policy_row,
    platform_block_length,
    render_policy_block,
)

router = APIRouter()


def _to_out(
    row: SystemPolicy | None, *, updated_by_username: str | None = None
) -> PolicyOut:
    """把 DB 单行（或 None）转成响应体，并算出 preview。"""
    if row is None:
        enabled = True
        rules: list[PolicyRule] = []
        updated_at = None
    else:
        enabled = bool(row.enabled)
        raw_rules = row.rules or []
        rules = [
            PolicyRule(
                id=r.get("id"),
                title=r.get("title") or "",
                content=r.get("content") or "",
                enabled=bool(r.get("enabled", True)),
            )
            for r in raw_rules
            if isinstance(r, dict)
        ]
        updated_at = row.updated_at
    preview = render_policy_block(
        enabled=enabled,
        rules=[r.model_dump() for r in rules],
        # preview 只展示平台段，不含任何具体群的 notice。
        group_notice=None,
    )
    return PolicyOut(
        enabled=enabled,
        rules=rules,
        preview=preview,
        updated_at=updated_at,
        updated_by_username=updated_by_username,
    )


async def _updated_by_username(
    session: AsyncSession, row: SystemPolicy | None
) -> str | None:
    if row is None or row.updated_by is None:
        return None
    user = await session.get(User, row.updated_by)
    return user.username if user else None


@router.get("", response_model=PolicyOut)
async def get_policy(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_user),
) -> PolicyOut:
    """读取平台群规。未配置过时返回默认值（enabled=true, rules=[], preview=null）。"""
    row = await load_policy_row(session)
    return _to_out(row, updated_by_username=await _updated_by_username(session, row))


@router.put("", response_model=PolicyOut)
async def update_policy(
    payload: PolicyUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> PolicyOut:
    """整表替换平台群规（upsert 单行）。仅管理员。"""
    # 规范化：补 id、去空白、丢掉完全空的规则。
    normalized: list[dict] = []
    for r in payload.rules:
        title = (r.title or "").strip()
        content = (r.content or "").strip()
        if not title and not content:
            continue
        normalized.append(
            {
                "id": (r.id or "").strip() or uuid.uuid4().hex[:8],
                "title": title,
                "content": content,
                "enabled": bool(r.enabled),
            }
        )

    # 保存前按「未截断」的正文长度校验。注意不能用 render_policy_block 的
    # 结果来判：它本身就会把平台段截断到 MAX_PLATFORM_BLOCK，拿截断后的
    # 长度去比上限永远不成立，超出的规则会被静默丢弃而管理员毫无感知。
    estimated = platform_block_length(normalized)
    if estimated > MAX_PLATFORM_BLOCK:
        raise HTTPException(
            status_code=400,
            detail=(
                f"平台群规总长度 {estimated} 字符，超出上限 {MAX_PLATFORM_BLOCK} 字符，"
                "请精简后重试"
            ),
        )

    row = await load_policy_row(session)
    if row is None:
        row = SystemPolicy(id=POLICY_ROW_ID, enabled=payload.enabled, rules=normalized)
        session.add(row)
    else:
        row.enabled = payload.enabled
        row.rules = normalized
    row.updated_by = user.id
    await session.flush()

    await audit_service.log(
        session,
        ctx,
        action="policy.update",
        target_type="policy",
        target_id=str(POLICY_ROW_ID),
        target_name="平台群规",
        detail={"enabled": payload.enabled, "rule_count": len(normalized)},
    )
    await session.commit()
    await session.refresh(row)
    return _to_out(row, updated_by_username=user.username)
