"""Bot (character) CRUD endpoints + per-bot skill associations."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Bot, BotSkill, Skill
from app.db.session import get_session
from app.schemas import BotCreate, BotOut, BotSkillOut, BotSkillSet, BotUpdate, SkillOut

router = APIRouter()


@router.get("", response_model=list[BotOut])
async def list_bots(session: AsyncSession = Depends(get_session)) -> list[Bot]:
    result = await session.execute(select(Bot).order_by(Bot.id))
    return list(result.scalars().all())


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(
    payload: BotCreate, session: AsyncSession = Depends(get_session)
) -> Bot:
    bot = Bot(**payload.model_dump())
    session.add(bot)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="bot name must be unique")
    await session.refresh(bot)
    return bot


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(bot_id: int, session: AsyncSession = Depends(get_session)) -> Bot:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return bot


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: int, payload: BotUpdate, session: AsyncSession = Depends(get_session)
) -> Bot:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    data = payload.model_dump(exclude_none=True)
    # System bots have a fixed identity (name/model) so the orchestrator
    # can keep referring to them by name without drift. Persona, temperature,
    # params, emoji, avatar_url are still editable.
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
    for k, v in data.items():
        setattr(bot, k, v)
    await session.commit()
    await session.refresh(bot)
    return bot


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(bot_id: int, session: AsyncSession = Depends(get_session)) -> None:
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
    bot_id: int, session: AsyncSession = Depends(get_session)
) -> list[BotSkillOut]:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return await _bot_skill_outs(session, bot_id)


@router.put("/{bot_id}/skills", response_model=list[BotSkillOut])
async def set_bot_skills(
    bot_id: int, payload: BotSkillSet, session: AsyncSession = Depends(get_session)
) -> list[BotSkillOut]:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")

    # Validate all requested skill ids exist.
    skill_ids = list(dict.fromkeys(payload.skill_ids))  # dedupe, keep order
    if skill_ids:
        result = await session.execute(select(Skill).where(Skill.id.in_(skill_ids)))
        found = {s.id for s in result.scalars().all()}
        missing = [sid for sid in skill_ids if sid not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"技能不存在: {missing}")

    # Replace the bot's enabled skill set with the requested ids.
    await session.execute(delete(BotSkill).where(BotSkill.bot_id == bot_id))
    for sid in skill_ids:
        session.add(BotSkill(bot_id=bot_id, skill_id=sid, enabled=True))
    await session.commit()
    return await _bot_skill_outs(session, bot_id)