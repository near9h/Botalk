"""Message history endpoints. Wire-facing 用 `group_public_id`."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runs import _resolve_visible_group
from app.auth import require_user
from app.db.models import Attachment, Message, User
from app.db.session import get_session
from app.schemas import MessageOut
from app.services import audit as audit_service

router = APIRouter()


@router.get("", response_model=list[MessageOut])
async def list_messages(
    group_public_id: str = Query(..., description="Group public id"),
    run_id: int | None = Query(default=None, description="Optional session filter"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[Message]:
    group = await _resolve_visible_group(session, user, group_public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    stmt = select(Message).where(Message.group_id == group.id)
    if run_id is not None:
        stmt = stmt.where(Message.run_id == run_id)
    result = await session.execute(stmt.order_by(Message.id.asc()).limit(limit))
    rows = list(result.scalars().all())

    # Translate any legacy int ids in `attachments` to public_ids so the
    # frontend (which keys its metadata cache by public_id) gets a
    # consistent shape regardless of when the row was written.
    int_ids: set[int] = set()
    for m in rows:
        for ref in (m.attachments or []):
            if isinstance(ref, int):
                int_ids.add(ref)
    id_to_public: dict[int, str] = {}
    if int_ids:
        att_rows = (
            await session.execute(
                select(Attachment.id, Attachment.public_id).where(Attachment.id.in_(int_ids))
            )
        ).all()
        id_to_public = {aid: pub for aid, pub in att_rows}
    for m in rows:
        m.attachments = [
            id_to_public[ref] if isinstance(ref, int) and ref in id_to_public
            else (str(ref) if isinstance(ref, int) else ref)
            for ref in (m.attachments or [])
        ]
    return rows


@router.delete("", status_code=204)
async def clear_messages(
    group_public_id: str = Query(..., description="Group public id"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    """Delete every message in the given group — used by the chat UI's
    "↻ 清空对话" button to start a fresh thread within the same group."""
    group = await _resolve_visible_group(session, user, group_public_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    if user.role != "admin" and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只能清空自己创建的群组")
    await session.execute(
        delete(Message).where(Message.group_id == group.id)
    )
    await audit_service.log(
        session,
        ctx,
        action="message.clear",
        target_type="group",
        target_id=group.public_id,
        target_name=group.name,
    )
    await session.commit()