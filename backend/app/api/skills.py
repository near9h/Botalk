"""Skill center CRUD + import endpoints."""
from __future__ import annotations

import io
import re
import uuid
import zipfile
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import BotSkill, Skill
from app.db.session import get_session
from app.schemas import (
    SkillAssetUpdate,
    SkillCreate,
    SkillImportMcp,
    SkillImportUrl,
    SkillOut,
)
from app.services import mcp as mcp_service

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
    result = await session.execute(
        select(BotSkill.skill_id, func.count(BotSkill.bot_id)).group_by(BotSkill.skill_id)
    )
    return {skill_id: count for skill_id, count in result.all()}


@router.get("")
async def list_skills(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    result = await session.execute(select(Skill).order_by(Skill.builtin.desc(), Skill.id))
    skills = result.scalars().all()
    counts = await _bot_counts(session)
    return [_skill_dict(s, counts.get(s.id, 0)) for s in skills]


@router.post("", response_model=SkillOut, status_code=201)
async def create_skill(
    payload: SkillCreate, session: AsyncSession = Depends(get_session)
) -> SkillOut:
    key = payload.key.strip().lower() or _KEY_RE.sub("-", payload.name.strip().lower())
    existing = await session.execute(select(Skill).where(Skill.key == key))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"技能 key 已存在: {key}")
    skill = Skill(**payload.model_dump(), key=key)
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(skill_id: int, session: AsyncSession = Depends(get_session)) -> SkillOut:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    return _to_out(skill)


@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: int, payload: SkillCreate, session: AsyncSession = Depends(get_session)
) -> SkillOut:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    data = payload.model_dump()
    if skill.builtin and (data["type"] != skill.type or data["key"] != skill.key):
        raise HTTPException(status_code=403, detail="内置技能的类型/key 不可修改")
    for k, v in data.items():
        setattr(skill, k, v)
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: int, session: AsyncSession = Depends(get_session)) -> None:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    if skill.builtin:
        raise HTTPException(status_code=403, detail=f"内置技能「{skill.name}」不可删除")
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
    payload: SkillImportUrl, session: AsyncSession = Depends(get_session)
) -> SkillOut:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(payload.url)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"抓取 SKILL.md 失败: {exc}")
    return _to_out(await _save_skillmd(session, text, name=payload.name))


# ─────────────────────────── MCP import ───────────────────────────


@router.post("/import/mcp", response_model=SkillOut, status_code=201)
async def import_mcp(
    payload: SkillImportMcp, session: AsyncSession = Depends(get_session)
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


@router.get("/community/search")
async def community_search(q: str) -> list[dict[str, Any]]:
    if not settings.skill_market_api_url:
        raise HTTPException(status_code=501, detail="未配置 SKILL_MARKET_API_URL，社区搜索不可用")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                settings.skill_market_api_url,
                params={"q": q},
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"社区搜索失败: {exc}")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "results", "items", "servers", "skills"):
            if isinstance(data.get(k), list):
                return data[k]
        return [data]
    return []


# ─────────────────────────── template assets ───────────────────────────


def _docx_to_markdown(content: bytes) -> str:
    """Convert .docx to structured markdown via python-docx.

    Preserves heading levels (Heading 1/2/3 → #/##/###), bulleted and
    numbered lists, and tables (GFM pipe tables). Falls back to plain
    text if python-docx is missing or the file is malformed, so legacy
    uploads don't break the upload.
    """
    try:
        from docx import Document  # python-docx
    except Exception as exc:  # noqa: BLE001
        return f"(docx 解析失败: 缺少 python-docx ({exc}))"

    try:
        doc = Document(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        return f"(docx 解析失败: {exc})"

    lines: list[str] = []
    in_table = False
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        # GFM table: header + separator + body rows
        width = max(len(r) for r in table_rows)
        padded = [r + [""] * (width - len(r)) for r in table_rows]
        lines.append("| " + " | ".join(padded[0]) + " |")
        lines.append("| " + " | ".join(["---"] * width) + " |")
        for r in padded[1:]:
            lines.append("| " + " | ".join(r) + " |")
        lines.append("")
        table_rows = []

    for block in iter_block_items(doc):
        kind = block.get("kind")
        if kind == "table":
            rows = block["rows"]
            # First row acts as header
            table_rows = [list(rows[0])] + [list(r) for r in rows[1:]]
            in_table = True
            continue
        # any non-table block flushes an open table
        if in_table:
            flush_table()
            in_table = False
        if kind == "paragraph":
            p = block["paragraph"]
            style = (p.style.name or "").lower() if p.style else ""
            txt = (p.text or "").strip()
            if not txt:
                lines.append("")
                continue
            if "heading 1" in style:
                lines.append(f"# {txt}")
                lines.append("")
            elif "heading 2" in style:
                lines.append(f"## {txt}")
                lines.append("")
            elif "heading 3" in style:
                lines.append(f"### {txt}")
                lines.append("")
            elif "heading 4" in style:
                lines.append(f"#### {txt}")
                lines.append("")
            elif "heading 5" in style or "heading 6" in style:
                lines.append(f"##### {txt}")
                lines.append("")
            else:
                lines.append(txt)
                lines.append("")
        elif kind == "list":
            for item in block["items"]:
                marker = "-" if block["ordered"] is False else "1."
                lines.append(f"{marker} {item}")
            lines.append("")

    if in_table:
        flush_table()

    return "\n".join(lines).strip()


def iter_block_items(doc):
    """Yield paragraphs, lists, and tables in document order."""
    try:
        from docx.document import Document as _Doc
        from docx.oxml.ns import qn

        parent = doc.element.body
        for child in parent.iterchildren():
            tag = child.tag
            if tag == qn("w:p"):
                p = doc.paragraphs  # fallback path; the index lookup below is fine
                # python-docx exposes paragraphs by iterating document.paragraphs,
                # but for interleaved tables we walk the XML directly.
                from docx.text.paragraph import Paragraph
                yield {"kind": "paragraph", "paragraph": Paragraph(child, doc)}
            elif tag == qn("w:tbl"):
                from docx.table import Table
                tbl = Table(child, doc)
                rows = []
                for row in tbl.rows:
                    rows.append([cell.text.strip() for cell in row.cells])
                yield {"kind": "table", "rows": rows}
            elif tag == qn("w:sdt"):
                # content controls sometimes wrap a list — skip for now
                continue
    except Exception:
        # Final fallback: paragraphs only
        for p in doc.paragraphs:
            yield {"kind": "paragraph", "paragraph": p}


def _extract_text(filename: str, content: bytes) -> str:
    suffix = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if suffix in ("md", "markdown", "txt"):
        return content.decode("utf-8", errors="replace")
    if suffix == "docx":
        return _docx_to_markdown(content)
    return content.decode("utf-8", errors="replace")


def _read_assets(skill: Skill) -> list[dict[str, Any]]:
    """Return a *detached* list of asset dicts.

    SQLAlchemy's plain JSON column only fires an UPDATE when the top-level
    dict identity changes; nested `dict[k] = v` on a child dict that came
    straight from `skill.manifest` isn't always tracked (the children are
    plain dicts, not MutableDict wrappers). By deep-copying each asset we
    give callers a fully independent object: any mutation that the handler
    makes is captured when we reassign `skill.manifest` in `_write_assets`.

    Older assets only stored `{name, content_md}`; backfill id / description
    / is_default so the rest of the code can address them uniformly.
    """
    import copy
    out: list[dict[str, Any]] = []
    raw = (skill.manifest or {}).get("assets", [])
    for i, a in enumerate(raw):
        d = dict(a)
        d.setdefault("id", f"legacy-{i}")
        d.setdefault("description", "")
        d.setdefault("is_default", False)
        out.append(d)
    return out


def _write_assets(skill: Skill, assets: list[dict[str, Any]]) -> None:
    # Reassign the top-level manifest so SQLAlchemy emits an UPDATE. The
    # `assets` list passed in is already detached (see `_read_assets`).
    import copy
    manifest = copy.deepcopy(skill.manifest or {})
    manifest["assets"] = assets
    skill.manifest = manifest


@router.post("/{skill_id}/assets", response_model=SkillOut)
async def upload_asset(
    skill_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> SkillOut:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")

    suffix = Path_ext(file.filename or "").lower()
    if suffix and suffix not in _TEMPLATE_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"模板仅支持 .md / .markdown / .txt（{suffix} 不在范围内）",
        )

    raw = await file.read()
    text = _extract_text(file.filename or "template.txt", raw)
    if not text.strip():
        raise HTTPException(status_code=400, detail="模板内容为空")
    assets = _read_assets(skill)
    # First template becomes the default automatically; subsequent uploads
    # are non-default until the user promotes one.
    assets.append(
        {
            "id": uuid.uuid4().hex[:12],
            "name": file.filename or "template.txt",
            "description": "",
            "content_md": text,
            "is_default": len(assets) == 0,
        }
    )
    _write_assets(skill, assets)
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)


def Path_ext(filename: str) -> str:
    """Return the lowercased suffix including the dot, or ''."""
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


@router.patch("/{skill_id}/assets/{asset_id}", response_model=SkillOut)
async def update_asset(
    skill_id: int,
    asset_id: str,
    payload: SkillAssetUpdate,
    session: AsyncSession = Depends(get_session),
) -> SkillOut:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    assets = _read_assets(skill)
    target = next((a for a in assets if a.get("id") == asset_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    data = payload.model_dump(exclude_none=True)
    # Promoting a template to default clears the flag on all others.
    if data.get("is_default"):
        for a in assets:
            a["is_default"] = False
    for k, v in data.items():
        target[k] = v
    _write_assets(skill, assets)
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)


@router.delete("/{skill_id}/assets/{asset_id}", response_model=SkillOut)
async def delete_asset(
    skill_id: int,
    asset_id: str,
    session: AsyncSession = Depends(get_session),
) -> SkillOut:
    skill = await session.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    assets = _read_assets(skill)
    removed = next((a for a in assets if a.get("id") == asset_id), None)
    if removed is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    remaining = [a for a in assets if a.get("id") != asset_id]
    # If the default was removed, promote the first survivor so the skill
    # always resolves to a concrete template.
    if removed.get("is_default") and remaining:
        remaining[0]["is_default"] = True
    _write_assets(skill, remaining)
    await session.commit()
    await session.refresh(skill)
    return _to_out(skill)