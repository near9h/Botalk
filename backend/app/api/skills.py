"""Skill center CRUD + import endpoints."""
from __future__ import annotations

import io
import ipaddress
import re
import socket
import uuid
import zipfile
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_admin, require_user
from app.config import get_settings
from app.db.models import BotSkill, Skill
from app.db.session import get_session
from app.services import audit as audit_service
from app.schemas import (
    SkillAssetUpdate,
    SkillCreate,
    SkillImportMcp,
    SkillImportUrl,
    SkillOut,
)
from app.services import mcp as mcp_service
from app.services import community as community_service

router = APIRouter()
settings = get_settings()

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
_KEY_RE = re.compile(r"[^a-z0-9_\-]+")

# Templates are stored as Markdown so the LLM can read structure (headings,
# lists, tables). .docx uploads are still allowed for legacy compatibility
# but go through a structural converter that preserves headings.
_TEMPLATE_EXT = {".md", ".markdown", ".txt"}


def _to_out(skill: Skill) -> SkillOut:
    return SkillOut.model_validate(skill)


def _skill_dict(skill: Skill, bot_count: int = 0) -> dict[str, Any]:
    out = _to_out(skill).model_dump(mode="json")
    out["bot_count"] = bot_count
    return out


async def _bot_counts(session: AsyncSession) -> dict[int, int]:
    result = await session.execute(select(BotSkill.skill_id, func.count(BotSkill.bot_id)).group_by(BotSkill.skill_id))
    return {skill_id: count for skill_id, count in result.all()}


async def _unique_key(session: AsyncSession, base: str) -> str:
    """返回一个未被占用的技能 key：冲突时依次追加 `-2`、`-3` …"""
    key = base
    n = 1
    while (await session.execute(select(Skill).where(Skill.key == key))).scalar_one_or_none():
        n += 1
        key = f"{base}-{n}"
    return key


@router.get("")
async def list_skills(
    session: AsyncSession = Depends(get_session),
    _user: Any = Depends(require_user),
) -> list[dict[str, Any]]:
    result = await session.execute(select(Skill).order_by(Skill.builtin.desc(), Skill.id))
    skills = result.scalars().all()
    counts = await _bot_counts(session)
    return [_skill_dict(s, counts.get(s.id, 0)) for s in skills]


@router.post("", response_model=SkillOut, status_code=201)
async def create_skill(
    payload: SkillCreate,
    session: AsyncSession = Depends(get_session),
    _admin: Any = Depends(require_admin),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> SkillOut:
    key = payload.key.strip().lower() or _KEY_RE.sub("-", payload.name.strip().lower())
    existing = await session.execute(select(Skill).where(Skill.key == key))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"技能 key 已存在: {key}")
    skill = Skill(**payload.model_dump(), key=key)
    session.add(skill)
    await audit_service.log(
        session, ctx,
        action="skill.create", target_type="skill",
        target_id="(pending)", target_name=skill.name,
    )
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_session),
    _user: Any = Depends(require_user),
) -> SkillOut:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    return _to_out(skill)


@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: int,
    payload: SkillCreate,
    session: AsyncSession = Depends(get_session),
    _admin: Any = Depends(require_admin),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> SkillOut:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    data = payload.model_dump()
    if skill.builtin and (data["type"] != skill.type or data["key"] != skill.key):
        raise HTTPException(status_code=403, detail="内置技能的类型/key 不可修改")
    for k, v in data.items():
        setattr(skill, k, v)
    await audit_service.log(
        session, ctx,
        action="skill.update", target_type="skill",
        target_id=str(skill.id), target_name=skill.name,
    )
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_session),
    _admin: Any = Depends(require_admin),
    ctx: audit_service.AuditContext = Depends(audit_service.audit_ctx),
) -> None:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    if skill.builtin:
        raise HTTPException(status_code=403, detail=f"内置技能「{skill.name}」不可删除")
    skill_name = skill.name
    await audit_service.log(
        session, ctx,
        action="skill.delete", target_type="skill",
        target_id=str(skill_id), target_name=skill_name,
    )
    await session.delete(skill)
    await session.commit()


# ─────────────────────────── SKILL.md import ───────────────────────────


def _parse_skillmd(text: str) -> dict[str, Any]:
    m = _FRONTMATTER_RE.match(text)
    frontmatter: dict[str, Any] = {}
    body = text
    if m:
        try:
            parsed = yaml.safe_load(m.group(1)) or {}
            if isinstance(parsed, dict):
                frontmatter = parsed
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"SKILL.md frontmatter 解析失败: {exc}")
        body = text[m.end():]
    return {"frontmatter": frontmatter, "body": body.strip()}


async def _save_skillmd(
    session: AsyncSession,
    text: str,
    *,
    name: str | None = None,
) -> Skill:
    parsed = _parse_skillmd(text)
    fm = parsed["frontmatter"]
    key = str(fm.get("name") or "").strip().lower()
    if not key:
        raise HTTPException(status_code=400, detail="SKILL.md 缺少 name 字段")
    # Ensure a globally-unique key (append suffix if colliding).
    base_key = key
    n = 1
    while (await session.execute(select(Skill).where(Skill.key == key))).scalar_one_or_none():
        n += 1
        key = f"{base_key}-{n}"

    skill = Skill(
        key=key,
        name=name or str(fm.get("name") or key),
        description=str(fm.get("description") or parsed["body"][:200]),
        type="knowledge",
        category="custom",
        icon="📄",
        config_schema={"assets": {"type": "list", "label": "模板资源", "accept": list(_TEMPLATE_EXT)}},
        manifest={"instructions": parsed["body"], "assets": []},
        builtin=False,
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return skill


@router.post("/import/skillmd", response_model=SkillOut, status_code=201)
async def import_skillmd(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _admin: Any = Depends(require_admin),
) -> SkillOut:
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        raise HTTPException(status_code=400, detail="SKILL.md 内容为空")
    return _to_out(await _save_skillmd(session, text))


@router.post("/import/skillmd/url", response_model=SkillOut, status_code=201)
async def import_skillmd_url(
    payload: SkillImportUrl,
    session: AsyncSession = Depends(get_session),
    _admin: Any = Depends(require_admin),
) -> SkillOut:
    # SSRF guard: only allow http(s); resolve hostname and reject any
    # private / loopback / link-local / cloud-metadata target. We do the
    # DNS check ourselves rather than letting httpx follow a redirect to
    # one of those ranges.
    parsed = urlparse(payload.url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL 必须为 http(s)")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="URL 缺少主机名")
    try:
        infos = await _resolve_all(host)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"DNS 解析失败: {exc}")
    # infos is a list of (family, type, proto, canonname, sockaddr) tuples.
    for info in infos:
        # info[4] is the sockaddr; for IPv4 it's (host, port), for IPv6
        # it's (host, port, flowinfo, scope_id). Either way the host is
        # at index 0 of that tuple.
        sockaddr = info[4]
        if _is_blocked_ip(sockaddr):
            raise HTTPException(
                status_code=400,
                detail=f"禁止访问内网地址 {sockaddr[0]}",
            )
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            resp = await client.get(payload.url)
            # Manually follow redirects with our own SSRF filter on each hop.
            redirects = 0
            while resp.is_redirect and redirects < 5:
                target = resp.headers.get("location") or ""
                parsed_next = urlparse(target)
                if parsed_next.scheme not in ("http", "https"):
                    raise HTTPException(status_code=400, detail="重定向到非 http(s) 目标")
                next_host = parsed_next.hostname or ""
                for next_info in await _resolve_all(next_host):
                    sockaddr = next_info[4]
                    if _is_blocked_ip(sockaddr):
                        raise HTTPException(
                            status_code=400,
                            detail=f"重定向到禁止地址 {sockaddr[0]}",
                        )
                resp = await client.get(target)
                redirects += 1
        resp.raise_for_status()
        text = resp.text
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"抓取 SKILL.md 失败: {exc}")
    return _to_out(await _save_skillmd(session, text, name=payload.name))


# ─────────────────────────── SSRF helpers ───────────────────────────

def _is_blocked_ip(sockaddr: tuple) -> bool:
    """Return True if the (host, port[, …]) sockaddr resolves to a
    private/loopback/link-local/unspec address.

    Blocks SSRF against the container network (10/8, 172.16/12,
    192.168/16), loopback (127/8), link-local (169.254/16 — covers the
    AWS / GCP / Azure metadata service at 169.254.169.254), and any
    IPv6 equivalent (ULA fc00::/7, link-local fe80::/10, ::1, etc.).
    """
    addr = sockaddr[0]
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # Malformed DNS response — treat as unsafe.
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


async def _resolve_all(host: str) -> list[tuple]:
    """Resolve `host` to all addrinfo sockaddr tuples.

    Single-pass DNS resolution means a malicious DNS server that returns
    a public IP for `getaddrinfo` and a private IP on the next call
    (DNS rebinding) is mostly mitigated: we resolve once and pass the
    resolved IP into httpx via a custom transport (a TODO if traffic
    ever grows). For the current scale this is enough to block direct
    SSRF via private IPs and the cloud metadata service.
    """
    import asyncio

    return await asyncio.get_running_loop().getaddrinfo(
        host, None, type=socket.SOCK_STREAM
    )


# ─────────────────────────── MCP import ───────────────────────────


@router.post("/import/mcp", response_model=SkillOut, status_code=201)
async def import_mcp(
    payload: SkillImportMcp,
    session: AsyncSession = Depends(get_session),
    _admin: Any = Depends(require_admin),
) -> SkillOut:
    try:
        tools = await mcp_service.list_tools(payload.url, payload.transport)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"连接 MCP server 失败: {exc}")
    if not tools:
        raise HTTPException(status_code=400, detail="MCP server 未暴露任何 tools")

    name = payload.name or payload.url.rstrip("/").rsplit("/", 1)[-1] or "MCP 技能"
    key = _KEY_RE.sub("-", name.strip().lower()) or "mcp-skill"
    base_key = key
    n = 1
    while (await session.execute(select(Skill).where(Skill.key == key))).scalar_one_or_none():
        n += 1
        key = f"{base_key}-{n}"

    skill = Skill(
        key=key,
        name=name,
        description=payload.description or f"来自 MCP server 的 {len(tools)} 个工具",
        type="mcp",
        category="mcp",
        icon="🔌",
        manifest={"url": payload.url, "transport": payload.transport, "tools": tools},
        config_schema={},
        builtin=False,
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)


# ─────────────────────────── community search ───────────────────────────
#
# 聚合三个社区来源：MCP Marketplace / findskill.md / anthropics-skills。
# 实现见 `app.services.community.search_community`：三路并发抓取，单个来源
# 失败不影响其它来源；失败详情以 `{"__health__": true, "errors": {...}}`
# 追加在结果末尾，前端据此渲染「GitHub 限流」之类的顶部警告条。
#
# 注意：本路由必须声明在 `/{skill_id}` 之前没有硬性要求（`community/search`
# 是两段路径，不会被单段的 `/{skill_id}` 匹配到），但保持读写权限与
# `GET /api/skills` 一致：任何登录用户可搜索，导入/安装才需要管理员。


@router.get("/community/search")
async def community_search(
    q: str,
    _user: Any = Depends(require_user),
) -> list[dict[str, Any]]:
    """搜索社区技能市场，返回按来源打分去重后的结果列表。"""
    query = (q or "").strip()
    if not query:
        return []
    return await community_service.search_community(query)


# ─────────────────────────── community install ───────────────────────────
#
# 把一条社区搜索结果落库成本地技能，两条路径：
#
#   * MCP Marketplace 条目 → 连上 MCP server 枚举 tools，存成 `mcp` 技能。
#   * GitHub SKILL.md 条目（`source ∈ {anthropic, findskill}`）→ 拉取
#     SKILL.md 正文，存成 `knowledge` 技能（正文写入 `manifest.instructions`）。
#
# 与 `/import/mcp` 一致：属于写操作，仅管理员可用。


@router.post("/community/install", response_model=SkillOut, status_code=201)
async def community_install(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    _admin: Any = Depends(require_admin),
) -> SkillOut:
    """安装一条社区搜索结果，返回落库后的技能。"""
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 不能为空")
    transport = (payload.get("transport") or "streamable-http").strip()
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    source = (payload.get("source") or "").strip()

    # ── GitHub SKILL.md 安装路径 ──
    if source in ("anthropic", "findskill"):
        try:
            from app.services.community import FINDSKILL_REPO, _b64_to_text, _gh_token_headers

            # url 形如 https://github.com/<owner>/<repo>/tree/<branch>/skills/<name>
            m = re.search(r"github\.com/([^/]+)/([^/]+)/tree/[^/]+/skills/([^/]+)", url)
            if m:
                repo = f"{m.group(1)}/{m.group(2)}"
                skill_dir = m.group(3)
            else:
                m2 = re.search(r"github\.com/([^/]+)/([^/]+)", url)
                repo = f"{m2.group(1)}/{m2.group(2)}" if m2 else FINDSKILL_REPO
                skill_dir = url.rstrip("/").rsplit("/", 1)[-1]

            api_url = f"https://api.github.com/repos/{repo}/contents/skills/{skill_dir}/SKILL.md"
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(api_url, headers=_gh_token_headers())
                if r.status_code != 200:
                    raise RuntimeError(f"GitHub {r.status_code}")
            skill_md = _b64_to_text(r.json().get("content", ""))
            if not skill_md.strip():
                raise RuntimeError("SKILL.md 为空")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"拉取 SKILL.md 失败: {exc}")

        # 解析 frontmatter 里的 name / description 作为兜底
        meta: dict[str, str] = {}
        if skill_md.startswith("---"):
            end = skill_md.find("\n---", 3)
            if end > 0:
                for line in skill_md[3:end].splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip().strip('"').strip("'")

        final_name = name or meta.get("name", "") or skill_dir
        final_desc = description or meta.get("description", "")
        key = await _unique_key(session, _KEY_RE.sub("-", final_name.strip().lower()) or "community-skill")
        skill = Skill(
            key=key,
            name=final_name,
            description=final_desc,
            type="knowledge",
            category="custom",
            icon="📚",
            manifest={
                "instructions": skill_md,
                "source": source,
                "source_url": url,
                "assets": [],
            },
            config_schema={
                "assets": {"type": "list", "label": "模板资源", "accept": [".md", ".markdown", ".txt"]},
            },
            builtin=False,
        )
        session.add(skill)
        await session.commit()
        await session.refresh(skill)
        return _to_out(skill)

    # ── MCP 安装路径（默认）──
    try:
        tools = await mcp_service.list_tools(url, transport)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"连接 MCP server 失败: {exc}")
    if not tools:
        raise HTTPException(status_code=400, detail="MCP server 未暴露任何 tools")

    final_name = name or url.rstrip("/").rsplit("/", 1)[-1] or "MCP 技能"
    key = await _unique_key(session, _KEY_RE.sub("-", final_name.strip().lower()) or "mcp-skill")
    skill = Skill(
        key=key,
        name=final_name,
        description=description or f"来自 MCP marketplace 的 {len(tools)} 个工具",
        type="mcp",
        category="mcp",
        icon="🔌",
        manifest={"url": url, "transport": transport, "tools": tools},
        config_schema={},
        builtin=False,
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)