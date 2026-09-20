# 05 详细设计（Detailed Design）

> PMBOK 第 7 章：从架构到落地的中间层 — 模块、接口、数据契约。

---

## 1. 模块清单

### 1.1 后端 API 模块（`backend/app/api/`）

| 模块 | 路由前缀 | 关键端点 |
| --- | --- | --- |
| `auth.py` | `/api/auth` | login / logout / register / me |
| `users.py` | `/api/users` | 列表 / 创建 / 改密 / 删 |
| `bots.py` | `/api/bots` | CRUD + `q/limit/offset` 搜索分页 |
| `models.py` | `/api/models` | 转发 NewAPI `/v1/models` |
| `groups.py` | `/api/groups` | CRUD + 加入 / 移除机器人 |
| `messages.py` | `/api/messages` | 列表 / 删除 |
| `chat.py` | `/api/chat` | `stream`（SSE） / `load_prior_history` |
| `runs.py` | `/api/runs` | 流式历史回看 |
| `tasks.py` | `/api/tasks` | 飞书任务代理 |
| `skills.py` | `/api/skills` | 技能列表 / 注册 |
| `kb.py` | `/api/kb` | KB CRUD + 上传 + chunk 预览 |
| `attachments.py` | `/api/attachments` | 上传 / 下载 / 预览 |
| `policies.py` | `/api/policies` | 群组策略（防火墙） |
| `audit.py` | `/api/audit` | 审计日志查询 |

### 1.2 后端 services（`backend/app/services/`）

| 模块 | 作用 |
| --- | --- |
| `audit.py` | 跨路由审计中间件 |
| `rag_retriever.py` | 主 RAG 检索（pgvector + BM25 + RRF 融合） |
| `local_retriever.py` | 本地 pgvector cosine + BM25 检索 |
| `citation_aligner.py` | chunk snippet ↔ 原文 对齐 |
| `sentence_window.py` | 上下文窗口扩展 |
| `ragflow_client.py` | **兼容 stub**（`is_configured()` 永远 `False`，不再调用） |
| `policy.py` | 群组策略执行（防火墙） |
| `community.py` | 群组动态聚类（探索性） |
| `language_detect.py` | 中英文启发式检测 |
| `mineru.py` | 文档解析包装 |
| `office_pdf.py` | Office→PDF（LibreOffice headless） |
| `zhipuai_embed.py` | Embedding（zhipuai） |
| `mcp.py` | MCP 协议适配 |

### 1.3 前端组件（`frontend/components/`）

| 组件 | 作用 |
| --- | --- |
| `Sidebar` | 全局侧边栏 + 路由 |
| `Composer` | 输入框 + 附件 |
| `ChatBubble` | 单条消息气泡（含引用 chip） |
| `CitedRefsFooter` | 引用脚注 |
| `CitationDrawerContext` | 引用抽屉全局状态 |
| `PdfViewerWithBbox` | PDF.js + bbox 标注 |
| `ChunkPreview` | 切片预览 |
| `AttachmentPreviewDrawer` | 附件预览抽屉 |
| `BotCard` / `BotFormDialog` | bot 卡片 / 编辑 |
| `GroupCard` / `GroupWizard` | 群组卡片 / 向导 |
| `KbUploader` | KB 上传组件 |
| `SourceCitation` | 单条引用渲染 |
| `TemplatePicker` | 模板选择 |
| `EmojiPicker` | 表情 |
| `ui.tsx` | 通用 UI 元件（Button/Input/Dialog…） |

### 1.4 前端路由（`frontend/app/`）

- `/` 首页（群组列表）
- `/bots` 机器人管理
- `/models` 模型浏览（NewAPI 中转）
- `/group/{id}` 单个群组聊天
- `/knowledge` KB 列表
- `/knowledge/{kb_id}` KB 详情
- `/skills` 技能中心
- `/admin` 管理面板
- `/login` / `/sse-test` 辅助

---

## 2. 接口契约（关键端点）

### 2.1 鉴权

```
POST /api/auth/login    { username, password } → 200 {MeOut} + Set-Cookie
POST /api/auth/logout                           → 204
GET  /api/auth/me                               → MeOut (require_user)
```

### 2.2 Bot

```
GET    /api/bots?q=&limit=20&offset=0   X-Total-Count 头
POST   /api/bots        { name, persona, model, temperature }
PATCH  /api/bots/{id}
DELETE /api/bots/{id}
```

### 2.3 KB（最近一期）

```
GET    /api/kb                           listKbs
POST   /api/kb                           createKb
GET    /api/kb/{kb_id}                   getKb
PATCH  /api/kb/{kb_id}                   updateKb      ← 新（ae0bae1）
DELETE /api/kb/{kb_id}                   deleteKb

GET    /api/kb/{kb_id}/documents                    listKbDocuments
POST   /api/kb/{kb_id}/documents  (multipart)       uploadKbDocument
GET    /api/kb/{kb_id}/documents/{doc_id}           getKbDocument
DELETE /api/kb/{kb_id}/documents/{doc_id}           deleteKbDocument
GET    /api/kb/{kb_id}/documents/{doc_id}/chunks    listKbDocumentChunks
GET    /api/kb/{kb_id}/documents/{doc_id}/preview   preview (PDF/HTML)
GET    /api/kb/{kb_id}/chunks/{chunk_id}            getKbChunk (bbox/snippet)
```

### 2.4 Chat 流式

```
POST /api/chat/stream   { group_id, prompt }   → SSE
   event: message   data: {"id":..,"role":"assistant","content":"...","bot_id":..}
   event: citation  data: {"chunk_id":..,"snippet":"...","page":..}
   event: done      data: {"run_id":..,"tokens":..}
```

完整 OpenAPI 由 FastAPI 在 `/docs` 自动暴露。

---

## 3. 数据契约

详细 JSON Schema 见 `backend/app/schemas.py`；前端 TS 类型见 `frontend/lib/api.ts`。

---

## 4. UI 设计

详见 [ui-redesign.md](ui-redesign.md)（从早期技术债而来）。

关键 UI 模式：

- **路由壳**：`PageShell`（顶部 + 侧边栏 + 内容区）
- **对话框**：复用 `components/ui.tsx` 的 `Dialog` + `DialogContent` + `DialogFooter`
- **流式渲染**：消息以块为单位替换，绝不刷新整页
- **PDF 预览**：sandbox iframe 装 PDF.js，画 bbox 用绝对定位 div
- **引用 chip**：`@@MENTION_n@@` 占位符二次替换，避免 markdown 解析阶段被破坏

---

## 5. 安全设计

| 边界 | 控制 |
| --- | --- |
| 用户密码 | bcrypt cost=12；不可逆 |
| 会话 | HttpOnly cookie；JWT |
| 跨域 | SameSite=lax；后续按需 CSP |
| KB 可见性 | `is_public` + `scope` (user/system) |
| API 权限 | `require_user` / `require_admin` 装饰器 |
| 审计 | 全写操作入 `audit_log` |

---

## 6. 相关链接

- [04 架构](../04-architecture/)
- [06 实现](../06-implementation/)
- [history/](../history/)（老方案）