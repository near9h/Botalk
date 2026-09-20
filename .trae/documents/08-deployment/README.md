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

## 2. 镜像清单

| 服务 | Dockerfile | 依赖 |
| --- | --- | --- |
| frontend | `frontend/Dockerfile` | Next.js 14 |
| backend | `backend/Dockerfile` | Python 3.11 + FastAPI + Alembic |
| nginx | `nginx/Dockerfile` | nginx:1.27 + 自定义 stream 路由 |
| postgres | pgvector/pg16（外部镜像） | — |

外部依赖（必须先就绪）：

- `new-api`（钙离子钙离子 / OpenAI 兼容网关）：URL + Key 在 `.env`
- `postgres`：自托管 pgvector 镜像

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
| `RAGFLOW_*` | (空) | 可选；不配则走本地检索 |

详见 [`.env.example`](../../../.env.example)。

---

## 6. 升级

见 [09-operations/upgrade.md](../09-operations/upgrade.md)。

---

## 7. 相关链接

- [04 架构](../04-architecture/)
- [09 运维](../09-operations/)