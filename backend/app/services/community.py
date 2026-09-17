"""Community skill discovery — 3 sources, deduped + scored.

Sources:

  1. MCP Marketplace.io   (`search_servers` tool over MCP)
     — credit: `mcp_marketplace`
     — score: uses the marketplace's `security.score` when available.
     — downloads: `use_cases` count or implicit (no public download metric).

  2. findskill.md        (`find-skills/findskill.md` GitHub README)
     — credit: `findskill`
     — score: GitHub stars of the README repo (proxy for popularity).
     — downloads: full clone count (`clone_url`-derived; we only have stars).

  3. Anthropic official  (`anthropics/skills` repo, top-level sub-dirs)
     — credit: `anthropic`
     — score: GitHub stars of the `anthropics/skills` repo.
     — downloads: `clones_count` from GitHub traffic API (if token set).

All three are fetched concurrently (`asyncio.gather`); partial failures
don't break the rest. The merged result is deduped by a stable key
(`(source, slug)` or `url`) and ranked by score.

Returned shape per item:

    {
      "id": str,
      "title": str,
      "description": str,
      "url": str,
      "remote_url": str | None,   # MCP endpoint if known
      "github_url": str | None,
      "transport": "streamable-http" | "sse" | None,
      "installable": bool,
      "source": "mcp_marketplace" | "findskill" | "anthropic",
      "score": float | None,     # higher = better, source-specific
      "downloads": int | None,   # when known
      "tags": [str],
      "raw": dict,                # source-specific extras (debug)
    }
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from app.config import get_settings
from app.services import mcp as mcp_service

settings = get_settings()

MARKETPLACE_URL = "https://mcp-marketplace.io/api/mcp/mcp"
MARKETPLACE_TRANSPORT = "streamable-http"

FINDSKILL_REPO = "addyosmani/agent-skills"
ANTHROPIC_REPO = "anthropics/skills"
GITHUB_API = "https://api.github.com"

# Per-source headers / auth
GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "botgroup-community-searcher",
}


def _gh_token_headers() -> dict[str, str]:
    """Add GitHub token if available (rate-limit: 60→5000 req/h)."""
    token = settings.github_token  # may be empty; ignore errors silently
    if token:
        return {**GH_HEADERS, "Authorization": f"Bearer {token}"}
    return dict(GH_HEADERS)


# ──────────────────────────── public API ────────────────────────────


async def search_community(query: str) -> list[dict[str, Any]]:
    """Return a deduplicated, scored, source-tagged result list."""
    query = (query or "").strip()
    if not query:
        return []

    # Track per-source health so the UI can surface "GitHub rate limited,
    # add GITHUB_TOKEN to .env" instead of silently showing fewer results.
    health: dict[str, str] = {}

    async def _safe(source: str, coro, warn_on_empty: bool = False) -> list[dict[str, Any]]:
        try:
            out = list(await coro)
            if warn_on_empty and not out:
                health[source] = "未返回结果（可能 GitHub 接口限流或仓库不存在）"
            return out
        except Exception as exc:
            health[source] = str(exc)[:200]
            return []

    mcp_results, findskill_results, anthropic_results = await asyncio.gather(
        _safe("mcp_marketplace", _search_mcp_marketplace(query)),
        _safe("findskill", _search_findskill(query), warn_on_empty=True),
        _safe("anthropic", _search_anthropic(query), warn_on_empty=True),
    )

    merged = mcp_results + findskill_results + anthropic_results
    deduped = _dedupe(merged)
    ranked = _rank(deduped, query)
    # Attach health info as a private suffix so the front-end can warn.
    if health:
        ranked.append({"__health__": True, "errors": health})  # type: ignore[arg-type]
    return ranked


# ──────────────────────────── source 1: MCP Marketplace ────────────────────────────


async def _search_mcp_marketplace(query: str) -> list[dict[str, Any]]:
    raw = await _call_tool_safe(
        MARKETPLACE_URL,
        MARKETPLACE_TRANSPORT,
        "search_servers",
        {"query": query},
    )
    base_items = _parse_marketplace(raw)
    if not base_items:
        return []

    # Hydrate each item with remote_url / github_url / installable.
    sem = asyncio.Semaphore(5)

    async def _hydrate(item: dict[str, Any]) -> dict[str, Any]:
        slug = item.get("id") or item.get("slug") or ""
        async with sem:
            detail_raw = await _call_tool_safe(
                MARKETPLACE_URL,
                MARKETPLACE_TRANSPORT,
                "get_server",
                {"slug": slug} if slug else {},
            )
        remote, github = _extract_remote(detail_raw)
        score = _extract_market_score(detail_raw)
        downloads = None
        if remote:
            item["url"] = remote
            item["remote_url"] = remote
            item["installable"] = True
        else:
            item["remote_url"] = None
            item["installable"] = False
        item["github_url"] = github
        item["source"] = "mcp_marketplace"
        item["score"] = score
        item["downloads"] = downloads
        item["raw"] = {"slug": slug}
        return item

    return await asyncio.gather(*[_hydrate(it) for it in base_items])


def _extract_market_score(raw: str) -> float | None:
    """Pull `security.score` (0–100) out of the get_server markdown."""
    if not raw:
        return None
    m = re.search(r'"score"\s*:\s*([\d.]+)', raw)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    m = re.search(r'"risk_level"\s*:\s*"([^"]+)"', raw)
    if m:
        # risk_level in {low, moderate, high, critical}; map to 0–100
        return {"low": 90, "moderate": 70, "high": 40, "critical": 10}.get(
            m.group(1).lower()
        )
    return None


# ──────────────────────────── source 2: findskill.md ────────────────────────────


async def _search_findskill(query: str) -> list[dict[str, Any]]:
    """List the `skills/` sub-dirs of addyosmani/agent-skills, read each
    SKILL.md frontmatter (name, description), and filter by query."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            contents_resp = await client.get(
                f"{GITHUB_API}/repos/{FINDSKILL_REPO}/contents/skills",
                headers=_gh_token_headers(),
            )
            repo_resp = await client.get(
                f"{GITHUB_API}/repos/{FINDSKILL_REPO}",
                headers=_gh_token_headers(),
            )
        if contents_resp.status_code == 403:
            raise RuntimeError("GitHub API 403（限流，请配置 GITHUB_TOKEN）")
        if contents_resp.status_code != 200:
            return []
        contents = contents_resp.json()
        stars = repo_resp.json().get("stargazers_count", 0) if repo_resp.status_code == 200 else 0
    except RuntimeError:
        raise
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(8)

    async def _fetch_one(entry: dict[str, Any]) -> dict[str, Any] | None:
        if entry.get("type") != "dir":
            return None
        name = entry.get("name", "")
        if name.startswith("."):
            return None
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.get(
                        f"{GITHUB_API}/repos/{FINDSKILL_REPO}/contents/skills/{name}/SKILL.md",
                        headers=_gh_token_headers(),
                    )
                if r.status_code != 200:
                    return None
                text = _b64_to_text(r.json().get("content", ""))
            except Exception:
                return None
        meta = _parse_skill_frontmatter(text)
        title = meta.get("name") or name
        desc = meta.get("description") or ""
        full = title + " " + desc
        if not _matches_query(full, query):
            return None
        gh = f"https://github.com/{FINDSKILL_REPO}/tree/main/skills/{name}"
        return {
            "id": f"findskill:{name}",
            "title": title,
            "description": desc[:400],
            "url": gh,
            "remote_url": None,
            "github_url": gh,
            "transport": None,
            "installable": True,  # installable via SKILL.md fetch
            "source": "findskill",
            "score": float(stars) if stars else None,
            "downloads": int(stars) if stars else None,
            "tags": [],
            "raw": {"dir": name},
        }

    tasks = [_fetch_one(c) for c in contents]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]


# ──────────────────────────── source 3: anthropics/skills ────────────────────────────


async def _search_anthropic(query: str) -> list[dict[str, Any]]:
    """List top-level sub-dirs of anthropics/skills, fetch each SKILL.md
    frontmatter (name, description), and filter by query."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            contents_resp = await client.get(
                f"{GITHUB_API}/repos/{ANTHROPIC_REPO}/contents/skills",
                headers=_gh_token_headers(),
            )
            repo_resp = await client.get(
                f"{GITHUB_API}/repos/{ANTHROPIC_REPO}",
                headers=_gh_token_headers(),
            )
        if contents_resp.status_code == 403:
            raise RuntimeError("GitHub API 403（限流，请配置 GITHUB_TOKEN）")
        if contents_resp.status_code != 200:
            return []
        contents = contents_resp.json()
        stars = repo_resp.json().get("stargazers_count", 0) if repo_resp.status_code == 200 else 0
    except RuntimeError:
        raise
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(8)

    async def _fetch_one(entry: dict[str, Any]) -> dict[str, Any] | None:
        if entry.get("type") != "dir":
            return None
        name = entry.get("name", "")
        if name.startswith("."):
            return None
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.get(
                        f"{GITHUB_API}/repos/{ANTHROPIC_REPO}/contents/skills/{name}/SKILL.md",
                        headers=_gh_token_headers(),
                    )
                if r.status_code != 200:
                    return None
                text = _b64_to_text(r.json().get("content", ""))
            except Exception:
                return None
        meta = _parse_skill_frontmatter(text)
        title = meta.get("name") or name
        desc = meta.get("description") or ""
        full = title + " " + desc
        if not _matches_query(full, query):
            return None
        gh = f"https://github.com/{ANTHROPIC_REPO}/tree/main/skills/{name}"
        return {
            "id": f"anthropic:{name}",
            "title": title,
            "description": desc[:400],
            "url": gh,
            "remote_url": None,
            "github_url": gh,
            "transport": None,
            "installable": True,  # installable via SKILL.md fetch
            "source": "anthropic",
            "score": float(stars) if stars else None,
            "downloads": int(stars) if stars else None,
            "tags": ["official"],
            "raw": {"dir": name},
        }

    tasks = [_fetch_one(c) for c in contents]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]


# ──────────────────────────── helpers ────────────────────────────


def _parse_skill_frontmatter(text: str) -> dict[str, Any]:
    """Pull YAML-ish frontmatter at the top of a SKILL.md (key: value)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = text[3:end].strip()
    out: dict[str, Any] = {}
    for line in fm.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _matches_query(text: str, query: str) -> bool:
    """Match if ANY query token appears in the haystack (OR, not AND).

    README / SKILL.md descriptions rarely repeat the user's exact
    keyword, so requiring every token usually drops everything. We
    prefer recall — the front-end ranks by score anyway.
    """
    haystack = text.lower()
    tokens = [t for t in re.split(r"\s+", query.lower()) if t]
    if not tokens:
        return True
    return any(t in haystack for t in tokens)


def _b64_to_text(b64: str) -> str:
    """Decode GitHub's base64 README/SKILL.md payloads (newline-tolerant)."""
    if not b64:
        return ""
    import base64
    try:
        return base64.b64decode(b64).decode("utf-8", errors="replace")
    except Exception:
        return ""


async def _call_tool_safe(url: str, transport: str, name: str, args: dict[str, Any]) -> str:
    try:
        return await mcp_service.call_tool(url, transport, name, args)
    except Exception:
        return ""


# ──────────────────────────── dedupe + ranking ────────────────────────────


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by `(source, slug)` or by normalized URL.

    For MCP marketplace entries we trust the slug (it's authoritative).
    Across sources we collapse entries that share the same GitHub repo
    (so the same skill indexed in two places becomes a single richer
    card with sources listed).
    """
    by_source_slug: dict[tuple[str, str], dict[str, Any]] = {}
    by_github: dict[str, str] = {}  # gh url -> key in by_source_slug

    for item in items:
        source = item.get("source") or "?"
        slug = item.get("id") or item.get("url") or ""
        gh = item.get("github_url") or ""
        if gh and gh in by_github:
            # merge into existing
            existing_key = by_github[gh]
            ex = by_source_slug[existing_key]
            ex["also_in"] = sorted(set((ex.get("also_in") or []) + [source]))
            # prefer a remote_url / score from the new item
            for k in ("remote_url", "url", "installable", "score", "downloads"):
                v = item.get(k)
                if v and not ex.get(k):
                    ex[k] = v
            continue

        # Source + slug identity check (avoid same source duplicating)
        # but allow distinct sources with the same slug.
        key = (source, slug)
        if key in by_source_slug:
            continue
        by_source_slug[key] = item
        if gh:
            by_github[gh] = key

    return list(by_source_slug.values())


def _rank(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Sort by source-priority then by score then by title-len desc."""
    source_priority = {
        "mcp_marketplace": 0,
        "anthropic": 1,
        "findskill": 2,
    }
    return sorted(
        items,
        key=lambda it: (
            source_priority.get(it.get("source") or "", 9),
            -(it.get("score") or 0),
            -len(it.get("title") or ""),
        ),
    )


# ──────────────────────────── legacy market parsers (kept) ────────────────────────────


def _parse_marketplace(raw: str) -> list[dict[str, Any]]:
    """Same logic as before for backwards compatibility with REST fallback."""
    if isinstance(raw, str):
        text = raw
        try:
            return _parse_marketplace(json.loads(text))
        except Exception:
            pass
        out: list[dict[str, Any]] = []
        for chunk in re.findall(r"```json\s*([\s\S]*?)```", text):
            try:
                out.extend(_flatten_marketplace(json.loads(chunk)))
            except Exception:
                pass
        if out:
            return out
        return _parse_markdown_table_safe(text)
    return _flatten_marketplace(raw)


_SLUG_RE = re.compile(r"[^a-z0-9_\-]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("-", s.lower()).strip("-")[:60] or "skill"


def _flatten_marketplace(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = None
        for k in ("servers", "results", "data", "items", "skills"):
            if isinstance(data.get(k), list):
                items = data[k]
                break
        items = items if items is not None else [data]
    else:
        items = []

    out: list[dict[str, Any]] = []
    for s in items:
        if not isinstance(s, dict):
            continue
        title = (
            s.get("displayName")
            or s.get("title")
            or s.get("name")
            or s.get("qualifiedName")
            or ""
        )
        qualified = s.get("qualifiedName") or s.get("id") or _slug(str(title))
        description = (s.get("description") or "")[:400]
        url = ""
        conn = s.get("connections")
        if isinstance(conn, list) and conn:
            url = (
                (conn[0].get("url") or conn[0].get("endpoint") or "")
                if isinstance(conn[0], dict)
                else ""
            )
        elif isinstance(conn, dict):
            url = conn.get("url") or conn.get("endpoint") or ""
        if not url:
            url = s.get("url") or s.get("homepage") or ""
        if not url:
            continue
        out.append(
            {
                "id": str(qualified),
                "title": str(title),
                "description": str(description),
                "url": str(url),
                "transport": str(s.get("transport") or "streamable-http"),
            }
        )
    return out


_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


def _parse_markdown_table(md: str) -> None:
    block: list[list[str]] = []
    for line in md.splitlines():
        if _TABLE_ROW.match(line):
            block.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif block:
            if len(block) >= 3:
                yield_block, block = block, []
                _emit_table_rows(yield_block)
            else:
                block = []
    if len(block) >= 3:
        _emit_table_rows(block)


_TABLE_ROWS: list[dict[str, Any]] = []


def _emit_table_rows(block: list[list[str]]) -> None:
    rows = [r for r in block if r and not all(set(c) <= {"-", " "} for c in r)]
    if len(rows) < 2:
        return
    for r in rows[1:]:
        if len(r) < 2:
            continue
        qualified = r[0].strip("` ")
        title = r[1].strip("` ") if len(r) > 1 else qualified
        description = r[2].strip() if len(r) > 2 else ""
        url = ""
        for cell in r:
            m = re.search(r"https?://\S+", cell)
            if m:
                url = m.group(0).rstrip(")>.,]")
                break
        if not url:
            continue
        _TABLE_ROWS.append(
            {
                "id": qualified,
                "title": title,
                "description": description[:400],
                "url": url,
                "transport": "streamable-http",
            }
        )


def _parse_markdown_table_safe(md: str) -> list[dict[str, Any]]:
    global _TABLE_ROWS
    _TABLE_ROWS = []
    list(_parse_markdown_table(md))
    return _TABLE_ROWS


# Used by search_via_marketplace's hydrate step
def _extract_remote(raw: str) -> tuple[str | None, str | None]:
    remote: str | None = None
    github: str | None = None
    if not raw:
        return remote, github
    try:
        for chunk in [raw] + re.findall(r"```json\s*([\s\S]*?)```", raw):
            try:
                data = json.loads(chunk)
                if isinstance(data, dict):
                    remote = data.get("remote_url") or remote
                    github = data.get("github_url") or github
            except Exception:
                pass
    except Exception:
        pass
    m = re.search(r'"remote_url"\s*:\s*"([^"]+)"', raw)
    if m and not remote:
        remote = m.group(1)
    m = re.search(r'"github_url"\s*:\s*"([^"]+)"', raw)
    if m and not github:
        github = m.group(1)
    return remote, github