"""Bot (character) CRUD + per-bot skill associations.

RBAC:
- GET /api/bots: admin 全集; user 仅看 scope='system' OR owner_id=self
- POST /api/bots: 普通用户自动 owner=self scope='user'; admin 可显式 scope='system'
- PATCH/DELETE: 非 owner 且非 admin → 403; system bot 保留 protected 校验

全部写操作接入 audit log。
"""
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_user
from app.config import get_settings
from app.db.models import Bot, BotKb, BotSkill, KnowledgeBase, Skill, User
from app.db.session import get_session
from app.schemas import BotCreate, BotOut, BotSkillOut, BotSkillSet, BotUpdate, SkillOut
from app.services import audit as audit_service

router = APIRouter()
settings = get_settings()


# Sentinel for "field absent from payload" — `None` is a valid value
# (e.g. kb_ids=[] means unmount everything) so we can't reuse `None`.
_UNSET = object()


# ─────────────────────────── helpers ───────────────────────────


async def _bot_to_out(bot: Bot, session: AsyncSession) -> BotOut:
    """Build BotOut and populate kb_ids + kb_public_ids from bot_kb.

    `kb_ids` / `kb_public_ids` are virtual fields — there's no
    `bot.kb_ids` ORM attribute (the association lives in the bot_kb
    table). We keep both: the integer list powers backend joins
    (e.g. local_retriever uses `kb_id` to filter the HNSW query),
    the public_id list is what the frontend uses to render
    `/knowledge/{token}` links.
    """
    out = BotOut.model_validate(bot)
    rows = (
        await session.execute(
            select(BotKb.kb_id, KnowledgeBase.public_id)
            .join(KnowledgeBase, KnowledgeBase.id == BotKb.kb_id)
            .where(BotKb.bot_id == bot.id)
            .order_by(BotKb.kb_id)
        )
    ).all()
    out.kb_ids = [r[0] for r in rows]
    out.kb_public_ids = [r[1] for r in rows]
    return out


async def _resolve_visible_kb(
    session: AsyncSession, kb_public_id: str, user: User
) -> KnowledgeBase:
    """Visibility for mounting a KB on a bot.

    Resolved via `KnowledgeBase.public_id` (the wire-facing token)
    instead of the integer pk, so the same string the user clicks in
    the UI is what the API accepts. Mirrors `api.kb._resolve_kb`:
    admin sees all, scope=system is global, is_public KBs are
    world-mountable, otherwise owner-only.
    """
    result = await session.execute(
        select(KnowledgeBase).where(KnowledgeBase.public_id == kb_public_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    if user.role == "admin" or kb.scope == "system" or kb.is_public:
        return kb
    if kb.owner_id == user.id:
        return kb
    raise HTTPException(status_code=404, detail="knowledge base not found")


@router.get("", response_model=list[BotOut])
async def list_bots(
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    q: str | None = Query(
        default=None, max_length=64,
        description="按机器人名称 icontains 过滤。前后空白会被剥除后匹配。",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[BotOut]:
    """admin 全集; user 仅看 system + 自己 owner + 别人分享的 (is_public) bot。

    支持简单分页 + 名称搜索（不分大小写）。响应头里附带 `X-Total-Count`，
    前端的下拉 / 列表据此决定要不要继续翻页。
    """
    # visibility filter — 先把可见 id 集取出来，count 与 fetch 复用同一份条件，
    # 这样 limit/offset 不会把总数算错。
    if user.role == "admin":
        visibility = select(Bot.id)
    else:
        visibility = select(Bot.id).where(
            or_(
                Bot.scope == "system",
                Bot.owner_id == user.id,
                Bot.is_public.is_(True),
            )
        )

    base_q = (
        select(Bot)
        .where(Bot.id.in_(visibility.subquery()))
        .order_by(Bot.id)
    )

    # `q` 是「按 name 过滤」的最小可用形态。`icontains` 走 ILIKE，对中文按字节
    # 匹配，已经够应付「输入『人事』找到『人事负责人』」这种需求；上 cover_ 后
    # 也只在名称里加 LIKE，复杂全文搜索不在当前范围。
    name_q = (q or "").strip()
    if name_q:
        base_q = base_q.where(Bot.name.ilike(f"%{name_q}%"))

    total = (
        await session.execute(
            select(func.count()).select_from(base_q.subquery())
        )
    ).scalar_one()
    if response is not None:
        response.headers["X-Total-Count"] = str(total)

    # 没东西直接返回空 list，省一次 KB 关联查询。
    if total == 0 or offset >= total:
        return []

    result = await session.execute(base_q.offset(offset).limit(limit))
    bots = list(result.scalars().all())
    if not bots:
        return []
    # Pre-load every bot's KB ids + public_ids in a single round-trip
    # (avoids N+1 — `_bot_to_out` would otherwise do one select per bot).
    bot_ids = [b.id for b in bots]
    kb_rows = await session.execute(
        select(BotKb.bot_id, BotKb.kb_id, KnowledgeBase.public_id)
        .join(KnowledgeBase, KnowledgeBase.id == BotKb.kb_id)
        .where(BotKb.bot_id.in_(bot_ids))
        .order_by(BotKb.bot_id, BotKb.kb_id)
    )
    by_bot: dict[int, list[int]] = {}
    by_bot_pid: dict[int, list[str]] = {}
    for bot_id, kb_id, public_id in kb_rows.all():
        by_bot.setdefault(bot_id, []).append(kb_id)
        by_bot_pid.setdefault(bot_id, []).append(public_id)
    out: list[BotOut] = []
    for b in bots:
        o = BotOut.model_validate(b)
        o.kb_ids = by_bot.get(b.id, [])
        o.kb_public_ids = by_bot_pid.get(b.id, [])
        out.append(o)
    return out


class GeneratePersonaRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    hint: str | None = Field(default=None, max_length=500)
    # 用户预期的人设输出语言：`"auto"`（默认，启发式从 name+hint 判定）、
    # `"zh"` 强制中文、`"en"` 强制英文。前端表单可让用户切换。
    language: str | None = Field(
        default=None,
        description='期望的人设输出语言：auto|zh|en。auto 时按名字与提示启发式判定。',
    )


class GeneratePersonaResponse(BaseModel):
    persona: str
    model: str
    latency_ms: int


def _persona_prompt(name: str, hint: str | None, lang: str) -> list[dict[str, str]]:
    """Build a small chat prompt that asks the model to write a system persona.

    输出直接落到 `bots.persona`，所以语种必须与期望回复一致 —— 不然后续
    群聊里 bot 会用 persona 的语种答而不是用户的语种。`lang` 来自
    `GeneratePersonaRequest.language`：`"zh"` / `"en"` 强制；`"auto"` /
    空字符串时按 `name + hint` 启发式判定（见
    `app.services.language_detect.detect_response_language`）。
    """
    extra = f"\n用户补充要求：{hint.strip()}" if hint and hint.strip() else ""
    if lang == "en":
        system = (
            "You are a senior prompt engineer who writes concise, distinctive "
            "system personas for multi-character group chat. Strictly follow "
            "the requirements: no markdown code blocks, no bullet points, no "
            "meta-explanations."
        )
        user = (
            f"Write a system prompt (persona) of about 200 words in English "
            f"for an AI character named 「{name.strip()}」, in 3 paragraphs:\n"
            "1) Identity & domain expertise (30-60 words)\n"
            "2) Tone & communication style (60-100 words)\n"
            "3) How it should respond when @-mentioned in a group chat, "
            "including its scope boundaries (60-80 words)\n"
            "The tone must suit the character implied by the name; do not "
            "repeat the name itself; do not start with 'You are a...' style "
            "meta-description."
            f"{extra}"
        )
    else:
        system = (
            "你是一名资深 Prompt 工程师，擅长为多角色群聊场景编写简洁、有辨识度的中文人设。"
            "请严格按要求输出，不要使用 markdown 代码块、不要使用项目符号、不要解释。"
        )
        user = (
            f"请为名为「{name.strip()}」的 AI 角色写一段中文 system prompt（人设），"
            "约 200 字，3 段：\n"
            "1) 身份与专业背景（30-60 字）\n"
            "2) 表达风格与沟通偏好（60-100 字）\n"
            "3) 在群聊中被 @ 时的回应方式与边界（60-80 字）\n"
            "语气需符合名字暗示的定位；不要重复名字本身；"
            "不要使用 '你是一位...' 之类的元描述开头。"
            f"{extra}"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


@router.post("/generate-persona", response_model=GeneratePersonaResponse)
async def generate_persona(
    body: GeneratePersonaRequest,
    user: User = Depends(require_user),
) -> GeneratePersonaResponse:
    """Ask NewAPI to draft a default persona for a freshly named bot.

    Used by the bot form dialog's "AI 生成" button next to the persona
    textarea. We pick a sensible default model (gpt-4o-mini when the
    configured NewAPI base URL is set) and surface the upstream error
    verbatim so the UI can show a useful message.
    """
    if not settings.newapi_base_url or settings.newapi_base_url.startswith(
        "https://your-newapi"
    ):
        raise HTTPException(
            status_code=503,
            detail="未配置 NewAPI（NEWAPI_BASE_URL），无法生成人设",
        )
    # Cheap, fast model is fine for short persona drafts; users can change
    # the bot's model after creation.
    model = "agnes-3.0-flash"
    url = f"{settings.newapi_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.newapi_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0.8,
        "max_tokens": 600,
        "stream": False,
    }
    # 解析期望的语种：`"zh"` / `"en"` 走强约束；其它（None / "auto" / 空串）
    # 视为自动，从 name + hint 启发式判定。
    lang = (body.language or "").lower()
    if lang not in ("zh", "en"):
        from app.services.language_detect import detect_response_language
        lang = detect_response_language(f"{body.name}\n{body.hint or ''}")
    payload["messages"] = _persona_prompt(body.name, body.hint, lang)
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"network error: {exc.__class__.__name__}: {exc}",
        ) from exc

    latency_ms = int((time.time() - started) * 1000)
    if resp.status_code != 200:
        # Try to surface the upstream message verbatim.
        err_text = resp.text[:300]
        try:
            err_json = resp.json()
            err = err_json.get("error") if isinstance(err_json, dict) else None
            if isinstance(err, dict) and err.get("message"):
                err_text = str(err["message"])[:300]
            elif isinstance(err, str):
                err_text = err[:300]
        except Exception:
            pass
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"NewAPI error: {err_text}",
        )

    try:
        data = resp.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        content = ""
        if choices:
            msg = choices[0].get("message") or {}
            raw = msg.get("content")
            if isinstance(raw, str):
                content = raw
            elif isinstance(raw, list):
                content = "".join(
                    p.get("text", "") for p in raw if isinstance(p, dict)
                )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"response parse error: {exc}",
        ) from exc

    persona = (content or "").strip()
    if not persona:
        raise HTTPException(status_code=502, detail="模型返回了空内容")

    return GeneratePersonaResponse(persona=persona, model=model, latency_ms=latency_ms)


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(
    payload: BotCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> BotOut:
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
    return await _bot_to_out(bot, session)


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(
    bot_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> BotOut:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if user.role != "admin" and bot.scope != "system" and bot.owner_id != user.id and not bot.is_public:
        raise HTTPException(status_code=404, detail="bot not found")
    return await _bot_to_out(bot, session)


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: int,
    payload: BotUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> BotOut:
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    # System bots are managed by the platform — only admin may touch them
    # at all (persona, model, temperature, skills, emoji, everything).
    if bot.is_system and user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"「{bot.name}」是系统机器人，仅管理员可修改",
        )
    # 权限：非 owner 且非 admin → 403
    if user.role != "admin" and bot.owner_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="只能修改自己创建的 bot",
        )
    data = payload.model_dump(exclude_none=True)
    # Protected (but non-system) bots: lock name + model, allow other fields
    if bot.is_protected and not bot.is_system:
        # Protected (non-system) bots were designed with their name and
        # model baked in; allow tweaking persona/temperature/emoji/skills
        # but not the name + model identity.
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
    # kb_public_ids is a virtual field — handled separately against bot_kb table.
    kb_public_ids_payload = data.pop("kb_public_ids", _UNSET)
    # Legacy `kb_ids` (integer PK) is still accepted but treated as a
    # hard error: we don't want stale callers sending ints and silently
    # matching against the wrong KB. The frontend already migrated.
    if "kb_ids" in data:
        raise HTTPException(
            status_code=400,
            detail="kb_ids 已弃用，请改用 kb_public_ids（wire-facing token）",
        )
    for k, v in data.items():
        setattr(bot, k, v)

    kb_diff: dict[str, list[str]] = {}
    if kb_public_ids_payload is not _UNSET:
        # Verify every KB the user wants to mount is visible to them.
        new_kbs: dict[int, str] = {}  # kb_id -> public_id
        for kpid in kb_public_ids_payload:
            kb = await _resolve_visible_kb(session, kpid, user)
            new_kbs[kb.id] = kb.public_id
        existing_rows = await session.execute(
            select(BotKb.kb_id, KnowledgeBase.public_id)
            .join(KnowledgeBase, KnowledgeBase.id == BotKb.kb_id)
            .where(BotKb.bot_id == bot.id)
        )
        existing = {r[0]: r[1] for r in existing_rows.all()}
        to_add = set(new_kbs) - set(existing)
        to_remove = set(existing) - set(new_kbs)
        # Idempotent insert (PK conflict → no-op). Composite (bot_id, kb_id).
        for kid in to_add:
            session.add(BotKb(bot_id=bot.id, kb_id=kid))
        if to_remove:
            await session.execute(
                delete(BotKb).where(
                    BotKb.bot_id == bot.id, BotKb.kb_id.in_(to_remove)
                )
            )
        kb_diff = {
            "added": sorted(new_kbs[k] for k in to_add),
            "removed": sorted(existing[k] for k in to_remove),
        }

    await audit_service.log(
        session,
        ctx,
        action="bot.update",
        target_type="bot",
        target_id=str(bot.id),
        target_name=bot.name,
        detail={
            "changed": list(data.keys()) + (["kb_public_ids"] if kb_diff else []),
            "is_public": bot.is_public,
            "kb_diff": kb_diff or None,
        },
    )
    await session.commit()
    await session.refresh(bot)
    return await _bot_to_out(bot, session)


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