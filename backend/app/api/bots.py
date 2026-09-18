"""Bot (character) CRUD + per-bot skill associations.

RBAC:
- GET /api/bots: admin 全集; user 仅看 scope='system' OR owner_id=self
- POST /api/bots: 普通用户自动 owner=self scope='user'; admin 可显式 scope='system'
- PATCH/DELETE: 非 owner 且非 admin → 403; system bot 保留 protected 校验

全部写操作接入 audit log。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_user
from app.db.models import Bot, BotSkill, Skill, User
from app.db.session import get_session
from app.schemas import BotCreate, BotOut, BotSkillOut, BotSkillSet, BotUpdate, SkillOut
from app.services import audit as audit_service

router = APIRouter()


@router.get("", response_model=list[BotOut])
async def list_bots(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[Bot]:
    """admin 全集; user 仅看 system + 自己 owner + 别人分享的 (is_public) bot。"""
    if user.role == "admin":
        result = await session.execute(select(Bot).order_by(Bot.id))
    else:
        result = await session.execute(
            select(Bot)
            .where(
                or_(
                    Bot.scope == "system",
                    Bot.owner_id == user.id,
                    Bot.is_public.is_(True),
                )
            )
            .order_by(Bot.id)
        )
    return list(result.scalars().all())


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(
    payload: BotCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> Bot:
    # 普通用户：忽略 client 传的 scope，强制 'user' 且 owner=self
    scope = payload.scope if user.role == "admin" else "user"
    if scope != "system":
        scope = "user"
    bot = Bot(
        **payload.model_dump(exclude={"scope"}),
        scope=scope,
        owner_id=user.id if scope == "user" else None,
    )
    session.add(bot)
    try:
        await session.flush()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="bot name must be unique")
    await audit_service.log(
        session,
        ctx,
        action="bot.create",
        target_type="bot",
        target_id=str(bot.id),
        target_name=bot.name,
        detail={"scope": bot.scope, "owner_id": bot.owner_id},
    )
    await session.commit()
    await session.refresh(bot)
    return bot


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(
    bot_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> Bot:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role != "admin" and bot.scope != "system" and bot.owner_id != user.id and not bot.is_public:
        raise HTTPException(status_code=404, detail="bot not found")
    return bot


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: int,
    payload: BotUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> Bot:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    # 权限：非 owner 且非 admin → 403
    if user.role != "admin" and bot.owner_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="只能修改自己创建的 bot",
        )
    data = payload.model_dump(exclude_none=True)
    # System bots: 保留现有 protected 校验（name / model 不可改）
    if bot.is_system or bot.is_protected:
        if "name" in data and data["name"] != bot.name:
            raise HTTPException(
                status_code=403,
                detail=f"「{bot.name}」是受保护机器人，名称不可修改",
            )
        if "model" in data and data["model"] != bot.model:
            raise HTTPException(
                status_code=403,
                detail=f"「{bot.name}」是受保护机器人，模型不可修改",
            )
    # is_public 字段只有 owner 或 admin 可以切换；system bot 永远 = True
    if "is_public" in data and not (user.role == "admin" or bot.owner_id == user.id):
        raise HTTPException(
            status_code=403, detail="只有创建者才能切换公开/私有"
        )
    for k, v in data.items():
        setattr(bot, k, v)
    await audit_service.log(
        session,
        ctx,
        action="bot.update",
        target_type="bot",
        target_id=str(bot.id),
        target_name=bot.name,
        detail={"changed": list(data.keys()), "is_public": bot.is_public},
    )
    await session.commit()
    await session.refresh(bot)
    return bot


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if bot.is_system:
        raise HTTPException(
            status_code=403,
            detail=f"系统机器人「{bot.name}」不可删除",
        )
    if bot.is_protected:
        raise HTTPException(
            status_code=403,
            detail=f"「{bot.name}」是受保护机器人，不可删除",
        )
    if user.role != "admin" and bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只能删除自己创建的 bot")
    bot_name = bot.name
    await audit_service.log(
        session,
        ctx,
        action="bot.delete",
        target_type="bot",
        target_id=str(bot.id),
        target_name=bot_name,
    )
    await session.delete(bot)
    await session.commit()


# ─────────────────────────── bot skills ───────────────────────────


async def _bot_skill_outs(session: AsyncSession, bot_id: int) -> list[BotSkillOut]:
    result = await session.execute(
        select(BotSkill)
        .options(selectinload(BotSkill.skill))
        .where(BotSkill.bot_id == bot_id)
        .order_by(BotSkill.skill_id)
    )
    return [
        BotSkillOut(
            skill=SkillOut.model_validate(bs.skill),
            config=bs.config or {},
            enabled=bs.enabled,
        )
        for bs in result.scalars().all()
    ]


@router.get("/{bot_id}/skills", response_model=list[BotSkillOut])
async def get_bot_skills(
    bot_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> list[BotSkillOut]:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role != "admin" and bot.scope != "system" and bot.owner_id != user.id:
        raise HTTPException(status_code=404, detail="bot not found")
    return await _bot_skill_outs(session, bot_id)


@router.put("/{bot_id}/skills", response_model=list[BotSkillOut])
async def set_bot_skills(
    bot_id: int,
    payload: BotSkillSet,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> list[BotSkillOut]:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role != "admin" and bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只能配置自己创建的 bot 的技能")

    skill_ids = list(dict.fromkeys(payload.skill_ids))
    if skill_ids:
        result = await session.execute(select(Skill).where(Skill.id.in_(skill_ids)))
        found = {s.id for s in result.scalars().all()}
        missing = [sid for sid in skill_ids if sid not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"技能不存在: {missing}")

    await session.execute(delete(BotSkill).where(BotSkill.bot_id == bot_id))
    for sid in skill_ids:
        session.add(BotSkill(bot_id=bot_id, skill_id=sid, enabled=True))
    await audit_service.log(
        session,
        ctx,
        action="bot.set_skills",
        target_type="bot",
        target_id=str(bot.id),
        target_name=bot.name,
        detail={"skill_ids": skill_ids},
    )
    await session.commit()
    return await _bot_skill_outs(session, bot_id)