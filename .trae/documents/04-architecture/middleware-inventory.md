# 中间件清单（Middleware Inventory）

> PMBOK § 7.1 / 运维交接必备。本目录登记 botgroup 依赖的全部中间件、容器、版本、端口、用途、来源。

---

## 1. 自建容器（仓库内 Dockerfile / docker-compose）

| 容器 | 镜像 / Dockerfile | 端口（内/外） | 用途 | 数据卷 |
| --- | --- | --- | --- | --- |
| `botgroup-frontend` | [`frontend/Dockerfile`](../../../frontend/Dockerfile) | 3000 / — | Next.js 14 SSR + 客户端 | — |
| `botgroup-backend` | [`backend/Dockerfile`](../../../backend/Dockerfile) | 8000 / — | FastAPI + uvicorn | `data/uploads/` |
| `botgroup-nginx` | [`nginx/Dockerfile`](../../../nginx/Dockerfile) | — / **3500** | 反代 + TLS 终结 + stream-routing | — |

---

## 2. 核心中间件（docker-compose 直接依赖）

| 容器 | 镜像 | 版本 | 端口 | 用途 | 关键配置 |
| --- | --- | --- | --- | --- | --- |
| `botgroup-postgres` | `pgvector/pgvector` | `pg16` | 5432 / — | 持久化 + 向量检索 | `POSTGRES_USER/PASSWORD/DB` 见 `.env`；初始建库由 entrypoint 跑 alembic |
| `new-api` | `calciumion/new-api` | `latest` | 5000 / — | OpenAI 兼容 LLM 网关（业务侧） | `NEWAPI_BASE_URL` / `NEWAPI_API_KEY` |

---

## 3. 可选 / 按需中间件

| 组件 | 用途 | 启用条件 | 备注 |
| --- | --- | --- | --- |
| **RAGFlow** | ❌ **不引入**。`backend/app/services/ragflow_client.py` 只是兼容 stub（`is_configured()` 永远 `False`）。详见 [ADR-0004](../adr/0004-kb-local-rag.md)。 |
| **MinerU** | PDF 文档解析 | KB 上传 PDF 时必走；Office 先转 PDF 再走 MinerU | 当前未容器化；运行时调外部 URL（`services/mineru.py`） |
| **LibreOffice headless** | Office → PDF 转换 | `services/office_pdf.py` 调用 | 装在 backend 容器内（Dockerfile `apt-get install libreoffice`） |
| **zhipuai embedding** | 向量生成 | `services/zhipuai_embed.py` | API 调用；无需容器 |

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

| 库 | 用途 |
| --- | --- |
| `fastapi` | Web 框架 |
| `uvicorn` | ASGI server |
| `sqlalchemy[asyncio]` | ORM async |
| `alembic` | 迁移 |
| `asyncpg` | PG async driver |
| `pgvector` | 向量列类型 |
| `pydantic` / `pydantic-settings` | schema + 配置 |
| `bcrypt` / `passlib` | 密码哈希 |
| `PyJWT` | 会话 token |
| `httpx` | 调 NewAPI / 智谱 GLM embedding |
| `openai` | OpenAI 兼容 SDK（NewAPI 客户端） |
| `python-multipart` | multipart 上传 |
| `pypdf` / `pdfplumber` | PDF 解析兜底 |
| `markdown-it-py` | markdown 渲染 |

详见 [`backend/pyproject.toml`](../../../backend/pyproject.toml)。

---

## 6. 前端依赖

| 库 | 用途 |
| --- | --- |
| `next` 14 | 框架 |
| `react` / `react-dom` | UI |
| `typescript` | 类型 |
| `pdfjs-dist` | PDF 预览（前端版） |
| `markdown-it` | markdown 渲染 |
| `event-source-polyfill` | 兼容旧浏览器的 EventSource |

详见 [`frontend/package.json`](../../../frontend/package.json)。

---

## 7. 端口全景

```
公网:
  3500/tcp  HTTPS  botgroup-nginx   ← 唯一对外

内网（容器间）:
  3000      frontend (next)
  8000      backend  (uvicorn)
  5000      new-api
  5432      postgres
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