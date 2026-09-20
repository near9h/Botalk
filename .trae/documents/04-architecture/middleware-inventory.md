# 中间件清单（Middleware Inventory）

> PMBOK § 7.1 / 运维交接必备。本目录登记 botgroup 依赖的全部中间件、容器、版本、端口、用途、来源。

---

## 1. 自建容器（仓库内 Dockerfile / docker-compose）

> 版本以**当前生产容器**实跑为准；CI 用 `:latest` 浮标时尽量打 digest 锁。

| 容器 | 基础镜像 | 跑版本（实际） | Dockerfile | 端口（内/外） | 用途 | 数据卷 |
| --- | --- | --- | --- | --- | --- | --- |
| `botgroup-frontend` | `node:20-alpine` | Node.js **20.20.2** | [`frontend/Dockerfile`](../../../frontend/Dockerfile) | 3000 / — | Next.js 14 SSR + 客户端 | — |
| `botgroup-backend` | `python:3.11-slim` (Debian 12 bookworm) | Python **3.11.16** | [`backend/Dockerfile`](../../../backend/Dockerfile) | 8000 / — | FastAPI + uvicorn + LibreOffice | `data/uploads/` |
| `botgroup-nginx` | `nginx:1.27-alpine` | nginx **1.27.5** | [`nginx/Dockerfile`](../../../nginx/Dockerfile) | — / **3500** | 反代 + TLS 终结 + stream-routing | — |

---

## 2. 核心中间件（docker-compose 直接依赖）

| 容器 | 镜像 | 跑版本（实际） | 端口 | 用途 | 关键配置 |
| --- | --- | --- | --- | --- | --- |
| `botgroup-postgres` | `pgvector/pgvector:pg16` | PostgreSQL **16.15** · pgvector 扩展 **0.8.6** | 5432 / — | 持久化 + 向量检索 | `POSTGRES_USER/PASSWORD/DB` 见 `.env`；初始建库由 entrypoint 跑 alembic |
| `new-api` | `calciumion/new-api:latest` | （未固定；业务侧容器，运行时拉） | 5000 / — | OpenAI 兼容 LLM 网关 | `NEWAPI_BASE_URL` / `NEWAPI_API_KEY` |

### 数据库 schema 版本（Alembic）

```bash
docker exec botgroup-postgres psql -U botgroup -d botgroup -tAc "SELECT version_num FROM alembic_version;"
```

当前 head：`0021_hybrid_search_bm25`（截至 2026-09-20）。

---

## 3. 可选 / 按需中间件

| 组件 | 版本 | 用途 | 启用条件 | 备注 |
| --- | --- | --- | --- | --- |
| **RAGFlow** | ❌ 不引入 | — | — | `backend/app/services/ragflow_client.py` 只是兼容 stub（`is_configured()` 永远 `False`）。详见 [ADR-0004](../adr/0004-kb-local-rag.md)。 |
| **MinerU** | MinerU Cloud API **v4** | PDF 文档解析 | KB 上传 PDF 时必走；Office 先转 PDF 再走 MinerU | 当前未容器化；运行时调 `https://mineru.net/api/v4`（`services/mineru.py`）；凭据 `MINERU_API_KEY` |
| **LibreOffice headless** | **25.2.3.2** (520 / Build 2) | Office → PDF 转换 | `services/office_pdf.py` 调用 | 装在 backend 容器内（Dockerfile `apt-get install libreoffice`） |
| **智谱 GLM embedding** | API：embedding-3（2048 dim）/ rerank | 向量生成 + 重排 | `services/zhipuai_embed.py` 调 `https://open.bigmodel.cn/api/paas` | API 调用，无容器 |

---

## 4. 上游 LLM（NewAPI 后面挂的）

| 模型 | 提供方 | 备注 |
| --- | --- | --- |
| `gpt-4o` / `gpt-4o-mini` / `gpt-5.4-mini` | OpenAI | 主力 |
| `claude-3-5-sonnet-20240620` | Anthropic | 长上下文 |
| `gemini-2.5-flash` | Google | 带 reasoning |
| `agnes-2.5-flash` / `agnes-3.0-flash` | (NewAPI 渠道) | |
| `MiniMax-M2.7` / `MiniMax-M3` | (NewAPI 渠道) | 长上下文 1M |

> botgroup **不直连厂商**，全部经 NewAPI。换厂商只改 `NEWAPI_BASE_URL`。

---

## 5. 第三方 Python 库（后端核心）

> 实跑版本 = `docker exec botgroup-backend pip show <pkg> | grep Version` 取自生产容器；
> 约束版本 = [`backend/pyproject.toml`](../../../backend/pyproject.toml) `dependencies`。

| 库 | 约束（pyproject） | 实跑（容器） | 用途 |
| --- | --- | --- | --- |
| `fastapi` | `>=0.115` | **0.141.1** | Web 框架 |
| `uvicorn[standard]` | `>=0.32` | — | ASGI server |
| `sqlalchemy[asyncio]` | `>=2.0.36` | **2.0.54** | ORM async |
| `alembic` | `>=1.14` | **1.20.0** | 迁移 |
| `asyncpg` | `>=0.30` | **0.31.0** | PG async driver |
| `pgvector` | (随 SQLAlchemy) | **0.8.6** | 向量列类型 |
| `pydantic` / `pydantic-settings` | `>=2.9` / `>=2.6` | **2.13.5** / **2.15.0** | schema + 配置 |
| `bcrypt` | `>=4.1` | **5.0.0** | 密码哈希 |
| `PyJWT` | `>=2.8` | **2.14.0** | 会话 token |
| `httpx` | `>=0.28` | **0.28.1** | 调 NewAPI / 智谱 GLM embedding |
| `openai` | `>=1.54` | **3.16.2** | OpenAI 兼容 SDK（NewAPI 客户端） |
| `python-multipart` | `>=0.0.9` | **0.0.32** | multipart 上传 |
| `markdown-it-py` | `>=3.0` | **4.2.0** | markdown 渲染 |
| `sse-starlette` | `>=2.1` | — | SSE 响应包装 |
| `mcp` | `>=1.0` | — | MCP 协议适配 |
| `jinja2` | `>=3.1` | — | 模板渲染（路线 B） |
| `python-docx` | `>=1.1` | — | .docx 解析 |
| `pypandoc-binary` | `>=1.13` | — | 嵌入式 pandoc（无需系统安装） |
| `slowapi` | `>=0.1.9` | — | 速率限制（安全审计项 A2） |

**未在本表**：LibreOffice（apt-get，不走 pyproject）、`passlib`（已迁移到 `bcrypt` 直接调用）。

---

## 6. 前端依赖

> 实跑版本取自 [`frontend/package.json`](../../../frontend/package.json)。

| 库 | 版本 | 用途 |
| --- | --- | --- |
| `next` | **14.2.15** | 框架（App Router） |
| `react` / `react-dom` | **18.3.1** | UI |
| `typescript` | **5.5.3** | 类型 |
| `@types/node` | 20.14.10 | Node 类型 |
| `@types/react` / `@types/react-dom` | 18.3.3 / 18.3.0 | React 类型 |
| `pdfjs-dist` | **4.7.76** | PDF 预览（前端版） |
| `markdown-it` | **14.1.0** | markdown 渲染 |
| `@types/markdown-it` | 14.1.2 | markdown-it 类型 |

---

## 7. 端口全景（含版本标注）

```
公网:
  3500/tcp  HTTPS  nginx 1.27.5          ← 唯一对外

内网（容器间，含版本）:
  3000      frontend (next 14.2.15 / node 20.20.2)
  8000      backend  (uvicorn + FastAPI 0.141.1 / Python 3.11.16)
  5000      new-api (calciumion/new-api:latest)
  5432      postgres 16.15 + pgvector 0.8.6
```

---

## 8. 数据卷清单

| 卷名 / 路径 | 挂到 | 备份策略 |
| --- | --- | --- |
| `pgdata` | postgres `/var/lib/postgresql/data` | 见 [09-operations/backup-restore.md](../09-operations/backup-restore.md) |
| `newapi-data` | new-api `/data` | 自带 |
| `./data/uploads/` | backend `/app/uploads` | 用户文件 + KB 文档源；纳入备份 |
| `frontend/.next/` | frontend `/app/.next` | **不备份**（构建产物） |
| `backend/.venv/` | backend `/app/.venv` | **不备份**（构建产物） |

---

## 9. 关键运维端口

- **管理 PG**：`docker exec -it botgroup-postgres psql -U botgroup -d botgroup`
- **看 NewAPI 日志**：`docker compose logs -f new-api`
- **后端进入容器调试**：`docker compose exec backend bash`
- **强制重建 backend**：`docker compose build --no-cache backend`

---

## 10. 关联文档

- [04-architecture/system-architecture.md](system-architecture.md) — 整体架构图
- [04-architecture/data-flow.md](data-flow.md) — 信息流向
- [08-deployment/README.md](../08-deployment/) — 部署清单
- [appendix/工具链清单.md](../appendix/工具链清单.md) — 工具 / 脚本