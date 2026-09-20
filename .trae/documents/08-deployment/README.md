# 08 部署（Deployment）

> PMBOK 第 12 章：项目执行 / 交付。本目录装交付链路的全部配置。

---

## 1. 一键启动

```bash
cd /opt/botgroup   # 或部署根
cp .env.example .env   # 改 NEWAPI_* 与 AUTH_*
docker compose up -d --build
docker compose logs -f backend   # 等 alembic upgrade head 完成
```

浏览器：`https://<host>:3500`

---

## 2. 镜像清单（生产实跑版本）

> 版本以**当前生产容器**实跑为准；
> 与 [04-architecture/middleware-inventory.md § 1–2](../04-architecture/middleware-inventory.md) 同步维护。

| 服务 | Dockerfile | 基础镜像 | 跑版本 | 用途 |
| --- | --- | --- | --- | --- |
| frontend | [`frontend/Dockerfile`](../../frontend/Dockerfile) | `node:20-alpine` | Node.js **20.20.2** · Next.js **14.2.15** · React **18.3.1** | SPA + 流式渲染 |
| backend | [`backend/Dockerfile`](../../backend/Dockerfile) | `python:3.11-slim` (Debian 12 bookworm) | Python **3.11.16** · FastAPI **0.141.1** · Alembic **1.20.0** · SQLAlchemy **2.0.54** · asyncpg **0.31.0** · LibreOffice **25.2.3.2** | API + 编排 + 文档解析 |
| nginx | [`nginx/Dockerfile`](../../nginx/Dockerfile) | `nginx:1.27-alpine` | nginx **1.27.5** | 反代 + TLS 终结 + stream-routing |
| postgres | `docker-compose.yml` | `pgvector/pgvector:pg16` | PostgreSQL **16.15** · pgvector **0.8.6** · Alembic head `0021_hybrid_search_bm25` | 持久化 + 向量 |
| new-api | `docker-compose.yml` | `calciumion/new-api:latest` | （浮动，业务侧容器） | OpenAI 兼容 LLM 网关 |

### 主要 Python / 前端库版本（详见 [04-architecture/middleware-inventory.md § 5–6](../04-architecture/middleware-inventory.md)）

| 库 | 版本 | 库 | 版本 |
| --- | --- | --- | --- |
| fastapi | 0.141.1 | next | 14.2.15 |
| sqlalchemy | 2.0.54 | react / react-dom | 18.3.1 |
| alembic | 1.20.0 | typescript | 5.5.3 |
| asyncpg | 0.31.0 | pdfjs-dist | 4.7.76 |
| pgvector | 0.8.6 | markdown-it | 14.1.0 |
| pydantic | 2.13.5 | | |
| bcrypt | 5.0.0 | | |
| PyJWT | 2.14.0 | | |
| httpx | 0.28.1 | | |
| openai | 3.16.2 | | |
| markdown-it-py | 4.2.0 | | |

外部依赖（必须先就绪）：

- `new-api`（钙离子钙离子 / OpenAI 兼容网关）：URL + Key 在 `.env`
- `postgres`：自托管 pgvector 镜像（已含 pgvector 扩展 0.8.6）

---

## 3. 网络 & 端口

| 端口（外） | 协议 | 服务 |
| --- | --- | --- |
| 3500 | HTTP + HTTPS | Nginx（stream 同时承载，靠首字节 0x16 分流） |
| 5432 | TCP | Postgres（仅内网） |

后端 + 前端**不直接对外**。

---

## 4. Nginx 关键设计

`nginx/nginx.conf`：

- `stream {}` 块在 3500 上做 TLS 嗅探 + proxy_protocol
- `http {}` 块分两个 server：3501（HTTP）/ 3500（Tunneled TLS）
- `proxy_protocol on` 配合 stream 的 PROXY header → 后端拿得到真实 client_ip

详见 [04-architecture/README.md § 4](../04-architecture/README.md)。

---

## 5. 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `POSTGRES_USER` | botgroup | |
| `POSTGRES_PASSWORD` | botgroup | **生产改** |
| `POSTGRES_DB` | botgroup | |
| `FRONTEND_PORT` | 3500 | Nginx 对外 |
| `NEWAPI_BASE_URL` | http://new-api:5000/v1 | |
| `NEWAPI_API_KEY` | (空) | **生产改** |
| `AUTH_SECRET` | (随机) | JWT 签名；首次启动时生成 |
| `AUTH_BOOTSTRAP_USER` | admin | 启动时若无用户则建 |
| `AUTH_BOOTSTRAP_PASSWORD` | admin | 同上 |
| `MAX_TOKENS_PER_CALL` | 2048 | |
| `REQUEST_TIMEOUT_SECONDS` | 120 | |
| `RAGFLOW_*` | (已移除) | **不再使用**。KB 检索走 pgvector + 智谱 GLM embedding（见 [ADR-0004](../adr/0004-kb-local-rag.md)） |

详见 [`.env.example`](../../../.env.example)。

---

## 6. 升级

见 [09-operations/upgrade.md](../09-operations/upgrade.md)。

---

## 7. 相关链接

- [04 架构](../04-architecture/)
- [09 运维](../09-operations/)