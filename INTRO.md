# botgroup · 框架与价值

> 一份给"还没看过仓库"的人准备的 5 分钟快速读物。

---

## 1. 项目一句话

**botgroup** 是一个多 AI 机器人协同讨论平台：把多个不同模型的 bot 拉进同一个"群组"，让它们按策略互相回应、互相引用，给出比单一模型更全面、更具对抗性的回答。

---

## 2. 它解决什么问题

| 单一 LLM 的痛 | botgroup 的解法 |
| --- | --- |
| 单一视角：保险核保 / 法律审阅 / 文档分析这种**多视角问题**，单模型要么只懂一半，要么编另一半 | **多 bot 并行 / 串行**，每个 bot 限定一个人设（如"专业核保员""合同律师""文档编辑"），综合意见 |
| 容易"自信地说错"：模型给出唯一答案时用户无从对照 | **三种发言策略**（auto / round_robin / manual） + 用户随时 `@bot名` 指定发言方 |
| 长上下文下引用难以溯源：模型说"根据文档第 3 章"，人工翻文档找不到 | **KB + 引用链路**：上传 PDF/Word/Excel，自动切分 + 嵌入检索，点击气泡里的 `[1]` 直接跳到 PDF 对应 bbox |
| 多轮对话上下文断裂：第 3 轮回答丢失前两轮内部状态 | **同任务 prior_history 注入** + 流式 SSE |
| 厂商绑定：换 GPT → Claude 要改一堆代码 | **只接 OpenAI 兼容协议**（NewAPI），换厂商只改 `NEWAPI_BASE_URL` 一个环境变量 |

---

## 3. 框架

### 3.1 技术栈

| 层 | 选型 | 理由 |
| --- | --- | --- |
| **后端** | FastAPI + SQLAlchemy 2.x（async）+ Alembic | 异步性能好；ORM 显式；迁移可审计 |
| **前端** | Next.js 14（App Router）+ TypeScript + 原生 EventSource | SSR + 流式零依赖 WebSocket |
| **数据库** | PostgreSQL 16 + pgvector 0.8 | 一份库解决"持久化 + 向量检索" |
| **LLM 网关** | NewAPI（OpenAI 兼容） | 不锁厂商，自托管 |
| **向量检索** | pgvector cosine + BM25 + RRF 融合 | 不引入额外 RAG 服务 |
| **文档解析** | MinerU（PDF）+ LibreOffice headless（Office→PDF） | 中文 OCR 强；Office 走转 PDF 路径统一管线 |
| **Embedding** | 智谱 GLM embedding-3（2048d） | 中文质量好；API 调用零容器 |
| **部署** | Docker Compose（单机一键） + Nginx stream-routing | 3500 端口同时承载 HTTP/HTTPS |
| **CI** | GitHub Actions（pytest + ruff + bandit + pip-audit + tsc） | 安全门禁；锁 runner 版本 |

### 3.2 模块结构

```
botgroup/
├── backend/                  FastAPI 服务
│   ├── app/
│   │   ├── api/              14 个路由模块（auth / bots / groups / kb / chat / ...）
│   │   ├── orchestrator/     多 bot 群聊调度核心（自研，参考 MsgHub）
│   │   ├── services/         13 个跨模块服务（audit / RAG / 解析 / 策略）
│   │   ├── skills/           技能注册中心
│   │   ├── workers/          后台 ingest 任务
│   │   ├── db/               ORM 模型 + async session
│   │   └── tools/            bot 可调用工具
│   ├── alembic/              迁移
│   └── tests/                pytest 单测
├── frontend/                 Next.js 应用
│   ├── app/                  10 个路由
│   ├── components/           20 个组件
│   └── lib/                  api 客户端 + markdown
├── nginx/                    自定义 stream-routing 配置
├── docker-compose.yml        单机一键
├── .env.example              环境变量模板
├── LICENSE                   MIT
└── INTRO.md                  ← 你正在读这份
```

### 3.3 数据流（端到端一句话聊天）

```
用户 → Nginx(3500 TLS) → FastAPI
        ↓
     msghub.run_group_discussion
        ↓ 对每个 bot 轮次
        ├─ language_detect → zh/en     跟随用户语种
        ├─ local_retriever               BM25 + pgvector + RRF
        ├─ NewAPI chat.completions      流式调上游模型
        └─ SSE event: message/citation  推送回浏览器
        ↓
     _summarize → 📋 总结（同语种）
        ↓
     audit_logs 入库（含真实 client_ip）
```

完整图见 [`.trae/documents/04-architecture/system-architecture.md`](.trae/documents/04-architecture/system-architecture.md)。

### 3.4 三种发言策略

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| `auto`（默认） | 一轮内所有 bot 都按加入顺序发言，LLM 决定何时停 | 多视角综合评审 |
| `round_robin` | 每轮只 1 个 bot，按加入顺序轮换 | 对抗辩论 / 头脑风暴 |
| `manual` | 仅当用户 `@bot名` 时被@的 bot 发言，否则退回轮换 | 节省 token / 精准对话 |

`max_rounds` 控制上限，默认 6。

### 3.5 KB + 引用

知识库 = Postgres 里的几张表 + pgvector 向量列 + 智谱 GLM embedding。

- **上传**：PDF 直接 MinerU；Word/Excel/PPT 先 LibreOffice 转 PDF 再 MinerU
- **检索**：BM25 + pgvector cosine，RRF 融合，top-5
- **引用**：LLM 在 system prompt 里看到 `[1] {snippet_1}` 这种引用块，回复里用 `[1]` 标注，前端替换为 `@@CITATION_1@@`，markdown 渲染为 cite-chip 按钮
- **溯源**：点 chip → 拉 `/api/kb/{id}/chunks/{chunk_id}` → bbox + snippet → PDF.js 跳页 + 画红框

---

## 4. 价值

### 4.1 对业务方

- **多模型评审不再昂贵**：以前想用 GPT + Claude + Gemini 交叉对照要切 3 个平台；现在一个群组就行
- **引用可信**：每个结论都能追到原文 bbox，避免"模型自信地说错"
- **知识沉淀**：上传企业文档 → bot 自动引用，**模型可解释性 = 100%**

### 4.2 对开发方

- **不锁厂商**：换 GPT / Claude / Gemini / 国内模型 只改一个环境变量
- **可观测**：所有写操作入 `audit_logs` 含真实 client_ip（通过 PROXY 协议）
- **可测试**：pytest + ruff + bandit + pip-audit + tsc 全套 CI 锁版本
- **可扩展**：技能中心 + tool-use 协议；新增 bot 工具 30 行 Python

### 4.3 对运维方

- **单机一键交付**：`docker compose up -d --build`，5 分钟起
- **5 份 Runbook**（备份 / 升级 / 应急 / On-call / 烟囱测试） + 1 份 post-mortem 模板
- **零外部 SaaS 依赖**：除 NewAPI 自托管外全部跑在 5 个本地容器里
- **容量基线** + docker stats 监控脚本（[09-operations](../.trae/documents/09-operations/)）

### 4.4 对安全审计

- 全量操作审计表 `audit_logs`（含 actor / client_ip / action / target）
- 三层 RBAC：admin / user + KB 可见性（`is_public` + `scope`）
- bcrypt cost=12 + HttpOnly cookie + SameSite=lax
- 内审报告见 [`.trae/documents/07-testing/security-audit-report.md`](.trae/documents/07-testing/security-audit-report.md)

---

## 5. 适用场景

| 行业 | 典型用法 |
| --- | --- |
| **保险** | 多产品核保员 bot 共审高风险保单；上传产品条款做合规对照 |
| **法律** | 合同律师 + 合规官 + 业务方三方评审合同；引用合同原文 |
| **产品 / 设计** | PRD 评审、用户访谈分析、竞品调研综述 |
| **教育 / 研究** | 多模型对同一论文做综述；不同视角回答学术问题 |
| **客服** | 多个 bot 共答 FAQ，按客户偏好路由到不同人设 |

---

## 6. 不适用场景

- 需要**工具调用 / 函数执行**的复杂 Agent（目前 skill 已支持但深度有限）
- 需要**多模态**输入（图像 / 音频）—— 当前仅文本 + PDF/Office 文档
- 需要**实时联网 / 搜索** — 公开搜索 key 可配但未内置
- **多租户 SaaS** — 当前单机单库，多租户需改造

---

## 7. 文档导航

| 我想看 | 路径 |
| --- | --- |
| 一图概览 + 端到端时序 | [`.trae/documents/04-architecture/system-architecture.md`](.trae/documents/04-architecture/system-architecture.md) |
| 中间件 + 版本 | [`.trae/documents/04-architecture/middleware-inventory.md`](.trae/documents/04-architecture/middleware-inventory.md) |
| 信息流向（6 条主数据流） | [`.trae/documents/04-architecture/data-flow.md`](.trae/documents/04-architecture/data-flow.md) |
| 4 份 ADR（关键决策） | [`.trae/documents/adr/`](.trae/documents/adr/) |
| 部署清单 | [`.trae/documents/08-deployment/README.md`](.trae/documents/08-deployment/README.md) |
| 运维 SOP（5 份） | [`.trae/documents/09-operations/`](.trae/documents/09-operations/) |
| 安全审计报告 | [`.trae/documents/07-testing/security-audit-report.md`](.trae/documents/07-testing/security-audit-report.md) |
| 项目 PMP 追踪 | [`.trae/documents/appendix/进度追踪表.md`](.trae/documents/appendix/进度追踪表.md) |

---

## 8. 快速上手

```bash
git clone https://github.com/<your-org>/botgroup.git
cd botgroup
cp .env.example .env       # 填你自己的 NewAPI URL + Key
docker compose up -d --build
# 等 backend 日志显示 "alembic upgrade head" 完成
# 打开 https://<your-host>:3500
```

详细步骤见 [README.md](README.md)。

---

## License

MIT — 见 [LICENSE](LICENSE)。