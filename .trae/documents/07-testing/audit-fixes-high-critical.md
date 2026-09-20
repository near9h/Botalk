# 方案：修复安全审计 critical + high 评级 5 项

## 摘要

根据 `.trae/documents/security-audit-report.md`，本 plan 修复最高 ROI 的 5 项问题：

| ID | 评级 | 摘要 | 工时 |
|----|------|------|------|
| **A1** | critical | 创建用户明文密码写进 audit log | 0.5h |
| **AC1** | high | `/api/attachments/batch-meta` 缺 `require_user` | 0.1h |
| **A4** | high | `.env` 文件权限 + 启动检查 | 0.5h |
| **A2** | high | 登录速率限制（slowapi） | 1h |
| **SS3** | high | MCP URL 白名单防 SSRF | 0.5h |

剩余 medium / low（cookie secure、密码策略、JWT TTL、文件路径、image pin、USER appuser 等）留作下一轮 plan。

---

## 调研结论：业内常见修法

| 问题 | 业内标准 |
|------|--------|
| 密码明文进 audit log | audit 仅记 `target_id + role`；密码通过响应一次性返回（保持现有 UX） |
| `/batch-meta` 缺鉴权 | 加 `Depends(require_user)` |
| `.env` 文件权限 | `chmod 600` + 启动时 `stat().st_mode & 0o077` 报错 |
| 登录速率限制 | slowapi（FastAPI 事实标准）+ IP+username 双维度计数；>5 次/分钟锁 5 分钟 |
| MCP URL 白名单 | `urlparse(url).hostname` 防 private IP / loopback；配置项 `MCP_ALLOWED_HOSTS` 显式 allowlist |

---

## 现状分析

| 文件 | 位置 | 当前实现 |
|------|------|---------|
| `api/users.py` | line 87-95 | `audit_service.log(... detail={"role": ..., "initial_password": password})` |
| `api/attachments.py` | line 355-358 | `@router.post("/batch-meta")` 仅 `Depends(get_session)` |
| `backend/.env` | host | `-rw-r--r--` 644；含明文 API keys |
| `api/auth.py` | line 55-87 | `login()` 无速率限制 |
| `services/mcp.py` | line 39-50 | `_client_context(transport, url)` 直接传 url 给 `sse_client` |

---

## 方案设计

### A1 · 创建用户 audit 不再记明文密码

**改动**（`backend/app/api/users.py:73-97`）：
- 删除 `detail` 里的 `initial_password`
- 改 `return user` 为 `return UserOut(...)` + `password_response = password` 单独传

**保持 UX**：把生成的 password 通过 `UserCreateOut` 响应一次性返回给 admin（前端页面已经显示）。**不写 audit，不进任何日志**。

**额外**：admin 在前端拿不到初始密码 = 用户拿不到 → 加 `must_change_password` flag，下次登录强制改密。但这是 UX 改造、不在本次修复范围——只做"密码不再进 audit"这一项。

### AC1 · `/batch-meta` 加 `require_user`

**改动**（`backend/app/api/attachments.py:355-359`）：
```python
@router.post("/batch-meta")
async def batch_attachment_meta(
    public_ids: list[str],
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),  # ← 新增
) -> list[dict]:
```

### A4 · `.env` 文件权限

**两处改动**：

1. **手动**：`chmod 600 backend/.env`（运维一次性操作）。
2. **启动检查**（`backend/app/main.py` lifespan 开头 + `app/config.py`）：

   ```python
   # app/main.py lifespan 第一行
   import os, stat
   env_path = Path(".env")
   if env_path.exists() and (env_path.stat().st_mode & 0o077):
       raise RuntimeError(
           f".env is world/group readable (mode={oct(env_path.stat().st_mode & 0o777)}); "
           "run `chmod 600 .env` before starting the backend."
       )
   ```
   
   - 仅检测 `.env`，不强制改（防止容器内 vs host 上行为不一致）
   - **dev 环境（本地开发）不影响**：本机 `chmod 600` 后启动报错才修

### A2 · slowapi 速率限制

**改动**：

1. **`backend/pyproject.toml`**：`slowapi>=0.1.9` 加入 dependencies
2. **`backend/app/main.py`**：
   ```python
   from slowapi import Limiter
   from slowapi.errors import RateLimitExceeded
   from slowapi.middleware import SlowAPIMiddleware
   from slowapi.util import get_remote_address
   
   limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
   app.state.limiter = limiter
   app.add_middleware(SlowAPIMiddleware)
   @app.exception_handler(RateLimitExceeded)
   async def _rate_limit_handler(request, exc):
       return JSONResponse({"detail": "请求过于频繁，请稍后再试"}, status_code=429)
   ```
3. **`backend/app/api/auth.py:login`**：
   ```python
   @router.post("/login")
   @limiter.limit("5/minute")  # IP 维度，每分钟 5 次登录尝试
   async def login(...):
   ```

**注意**：slowapi 默认 key_func 是 `get_remote_address`（即 `request.client.host`）。botgroup 通过 nginx `proxy_protocol` 注入真实 IP——但 `request.client.host` 在容器内可能拿到的是反代容器 IP。**生产场景需把 nginx 注入的 `X-Real-IP` 作为 key**。

**短期方案**：用 `get_remote_address`，配合 nginx 已设的 `X-Real-IP` 让 `request.client.host` 反映真实 IP（已有 nginx 配置 `set_real_ip_from 127.0.0.1; real_ip_header proxy_protocol` —— 但这只更新 `X-Real-IP` header，**不更新 `request.client.host`**）。

**正确做法**：自定义 `key_func`：
```python
def _real_client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or request.client.host or "unknown"
```

slowapi 在 init 时传这个函数。

### SS3 · MCP URL 白名单

**改动**（`backend/app/services/mcp.py` 加 `_assert_safe_mcp_url(url)`）：

```python
import ipaddress
from urllib.parse import urlparse

def _assert_safe_mcp_url(url: str) -> None:
    """Reject URLs that target private network space — defense in
    depth against an admin (or compromised-admin) configuring a
    malicious MCP URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"MCP URL scheme must be http(s); got {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("MCP URL missing host")
    # Try as IP literal first; fall back to DNS resolution.
    blocked = False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            blocked = True
    except ValueError:
        # Hostname — we don't DNS-resolve here (cost + TOCTOU); ops
        # should add the public domain to MCP_ALLOWED_HOSTS.
        from app.config import get_settings
        allowed = get_settings().mcp_allowed_hosts
        if host not in allowed:
            blocked = True
    if blocked:
        raise ValueError(
            f"MCP URL {url!r} targets private/reserved space or is not on the "
            "MCP_ALLOWED_HOSTS list. Refusing to connect (SSRF defense)."
        )
```

**改动**（`backend/app/config.py` 加 `mcp_allowed_hosts: list[str] = []`）。

**调用**（`backend/app/services/mcp.py:_client_context`）：
```python
def _client_context(transport: str, url: str):
    _assert_safe_mcp_url(url)  # ← 防御性 SSRF 校验
    ...
```

---

## 涉及文件清单

| 操作 | 路径 |
|------|------|
| 改 | `backend/app/api/users.py`（A1：删 detail.initial_password） |
| 改 | `backend/app/api/attachments.py`（AC1：加 require_user） |
| 改 | `backend/app/main.py`（A4：lifespan 加 .env 权限检查；A2：slowapi 接入） |
| 改 | `backend/app/api/auth.py`（A2：login 加 @limiter.limit） |
| 改 | `backend/app/services/mcp.py`（SS3：白名单校验） |
| 改 | `backend/app/config.py`（SS3：mcp_allowed_hosts） |
| 改 | `backend/pyproject.toml`（A2：slowapi 依赖） |

---

## 假设与决策

- **slowapi 默认 in-memory**：单一后端容器部署 OK；多后端容器需要 Redis。botgroup 当前 docker-compose 单 backend 容器，in-memory 够用。
- **MCP 白名单双层防护**：私有 IP（IP literal） + 显式 allowlist（hostname）。两层都做，因为 hostname-DNS 重绑定（TOCTOU）攻击下，单 IP 检查也会被绕开。
- **A1 不改响应**：admin 创建用户的响应仍是明文密码（一次性返回给 admin），**只是不进 audit log**。
- **A4 启动检查仅 warn 而非 raise**：dev 环境 `.env` 在 git 里也跑，权限不一定 600——用 `logger.warning` 而不是 `RuntimeError`，避免破坏现有 dev workflow。**生产环境**用 docker entrypoint 在容器内（host 上 `.env` 已经被 bind-mount 到容器，权限可能保留）——这一项产线下需要运维 `chmod 600`。

---

## 验证步骤

1. **A1**：admin 创建用户 → `GET /api/audit/logs?action=user.create` → detail 里**不**含 `initial_password` 字段；响应里仍返回明文密码给 admin ✅
2. **AC1**：未登录 `curl POST /api/attachments/batch-meta` → 401；登录后正常返回 ✅
3. **A4**：`chmod 644 .env && docker compose restart backend` → backend 启动时打 warning 日志 ✅
5. **A2**：`for i in $(seq 1 10); do curl -X POST localhost:3500/api/auth/login -d '{"username":"admin","password":"wrong"}' -H "Content-Type: application/json"; done` → 第 6 次开始返回 429 ✅
6. **SS3**：`curl -X POST localhost:3500/api/skills/import/mcp -d '{"url":"http://127.0.0.1:8000/api/auth/login"}' -H "Content-Type: application/json" -H "Cookie: botgroup_session=$ADMIN_TOKEN"` → 502 with "MCP URL ... targets private/reserved space" ✅

---

## 调研来源

- `.trae/documents/security-audit-report.md`（本轮 audit 报告）
- [slowapi documentation](https://slowapi.readthedocs.io/)
- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Python `ipaddress` module](https://docs.python.org/3/library/ipaddress.html)