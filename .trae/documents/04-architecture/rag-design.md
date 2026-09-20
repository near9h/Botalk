# 知识库 + RAG 接入计划（RAGFlow）

> 2026-09-19 · 面向 BotGroup 多 bot 群聊场景的本地知识库方案
> 选定框架：**RAGFlow** (Apache 2.0) · 智谱 GLM embedding + GLM rerank · PDF.js · MinerU OCR 沿用

---

## 0. 目标

| 维度 | 现在 | 目标 |
|---|---|---|
| 文档摄取 | 仅用户上传解析入 attachment | 用户上传 / 知识库挂载 → 入 RAGFlow dataset |
| 引用溯源 | 无 | 答案 markdown 标记 `[[source: filename p.X ¶Y]]`，前端 PDF.js 按 bbox 高亮 |
| 多 bot 共享 KB | 无 | KB ↔ bot 多对多挂载，群聊每个 bot 取自己 KB 合并检索 |
| rerank | 无 | 接入智谱 GLM rerank 接口，预留 BaseRanker slot |
| embedding | 无 | 智谱 GLM embedding（已有 HTTP 调用样板：可复用） |

**不在本期范围**：web 搜索 / 多模态图片问答 / 知识图谱 / RAG 评测平台。

---

## 1. 现状梳理

### 1.1 已具备
- FastAPI 后端 + SQLAlchemy 2.0 async + Alembic + PostgreSQL
- `Attachment` 表 + `storage_path` 字段 + `public_id` URL 令牌；[attachments.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/attachments.py) 已含 MinerU PDF/Word 解析（[attachments.py:178-196](file:///root/Drae_projects/botgroup/backend/app/api/attachments.py#L178-L196) `MinerU` 调用返回 bbox）
- `chat.py` SSE stream + [group_id 传给 generate_document_from_payload](file:///root/Documents/trae_projects/botgroup/backend/app/api/chat.py)
- `msghub.py` [OrchestratorEvent.attachments: list[dict]](file:///root/Documents/trae_projects/botgroup/backend/app/orchestrator/msghub.py#L91-L94) 已经能携带完整 AttachmentMeta 给前端
- 已建表 `bot_skills(bot_id, skill_id, enabled)` 关联 + alembic 路线 B backfill
- 前端 markdown.ts 已经能识别 `attachment://<public_id>` 链接 → AttachmentCards

### 1.2 缺什么
- 无知识库 / dataset / chunk 三层数据模型
- 无 retrieval pipeline（embedding / rerank / score threshold）
- 无 KB ↔ bot 关联表
- 无检索上下文注入 system prompt 机制
- 无引用渲染（`[[source: ...]]` 解析 + bbox 高亮）
- 无知识库管理 UI（上传 / 切片预览 / 删除 / 关联 bot）

### 1.3 关键调研结论（详见 plan §调研）
- **RAGFlow**：唯一同时满足 MinerU 接入 + bbox 引用 + 自定义 GLM embedding + rerank slot 的开源引擎（Apache 2.0）
- **LangChain / LlamaIndex / Haystack**：自接 MinerU + bbox 透传，需要自写 UI，工程量大
- **Dify**：License 实为 Apache 2.0 + 多租户 SaaS 附加条款，不合 MIT 严格约束
- **Verba / Quivr**：archived / 停滞，不选
- 智谱 GLM rerank 已开放 HTTP API，与现有 GLM embedding 调用模式一致

---

## 2. 架构总览

```
┌────────────────────────────────────────────────────────────────┐
│                        FastAPI (BotGroup)                       │
│                                                                │
│  /api/kb/*           /api/bots/{id}/kb/*        /api/chat/stream│
│      │                    │                          │         │
│      ▼                    ▼                          ▼         │
│  KB 管理服务  ────►   KB 关联服务        ChatOrchestrator        │
│      │                    │                  │                   │
│      │                    │                  ├─ 收集 bot KB 列表 │
│      │                    │                  ├─ 调 RAGFlow        │
│      │                    │                  │     /v1/retrieval   │
│      │                    │                  ├─ 拼 context 进 prompt│
│      │                    │                  └─ LLM 生成答案     │
│      ▼                                            │             │
│  MinerU 本地 OCR 服务 ◄──────────────────────────┘             │
│      │                                                          │
│      ▼                                                          │
│  RAGFlow HTTP API (docker compose, ≥4 容器)                   │
│   ├─ ragflow-server (Python + Go)                              │
│   ├─ mysql                                                      │
│   ├─ elasticsearch / infinity (向量 + 全文)                   │
│   ├─ minio (对象存储)                                          │
│   └─ nginx                                                      │
│                                                                │
│  向量 = GLM embedding（HTTP 调智谱）                          │
│  rerank = 智谱 GLM rerank API（HTTP 调智谱）                  │
│  LLM = 已有 NewAPI 代理（chat/completions）                    │
└────────────────────────────────────────────────────────────────┘

数据流（用户在知识库页上传 PDF）：
  1. FastAPI /api/kb/{id}/documents  接收 multipart
  2. 写 Attachment 表（status=parsing, source=user_upload, group_id=NULL）
  3. 后台 task: 调 MinerU → 拿到 bbox + text chunks
  4. 把 chunks 调 RAGFlow /v1/document/upload 传 "已有 OCR 结果" + bbox metadata
     （RAGFlow dataset 关闭内置 DeepDoc OCR，纯 ingest)
  5. RAGFlow 内部调 GLM embedding 写向量索引
  6. 更新 Attachment status=done, kb_document_id
  7. 前端轮询或 SSE 推送状态

数据流（bot 群聊触发 RAG 检索）：
  1. chat.py 拿到 user_prompt
  2. orchestrator 在每轮发言前检索：bot_id → 关联 kb 列表 → 每个 kb 调 RAGFlow /v1/retrieval/test
  3. 取 top_k chunks，按 page/bbox 排序去重
  4. 把 chunks 作为 system prompt 上下文：
     【知识库参考】
     [doc: filename.pdf p.3 ¶2]
     "....."
     [doc: filename.pdf p.5 ¶1]
     "....."
  5. LLM 返回答案，prompt 强制要求"使用 [doc: ...] 标注引用"
  6. 前端解析 [[source: filename p.X ¶Y]] → 调 /api/kb/chunks/{chunk_id} 拿 bbox → PDF.js overlay 高亮
```

---

## 3. 实施分阶段（5 个迭代）

> 每个迭代结束都是可上线状态、可回退。

### 阶段 1：基础设施（KB 数据模型 + 容器 + 接入）

**目标**：把 RAGFlow 跑起来 + BotGroup 与它对话。

后端：
- 新增 alembic 迁移 `0011_knowledge_base`：
  - `knowledge_bases(id, name, description, owner_id, scope, is_public, created_at)`
  - `kb_documents(id, kb_id, attachment_id, ragflow_doc_id, status, created_at)`
  - `kb_chunks(id, kb_doc_id, page, bbox_json, snippet, ragflow_chunk_id, created_at)`
  - `bot_kb(bot_id, kb_id)` 关联表
- 新建 `app/services/ragflow_client.py`：thin wrapper over httpx.AsyncClient，封装 `/v1/dataset/*` + `/v1/document/*` + `/v1/retrieval/*` + `/v1/chunk/*`（含超时/重试/认证）
- 配置 RAGFlow Docker Compose：
  - `infra/docker-compose.ragflow.yml`：ragflow-server + mysql + elasticsearch + minio + nginx
  - 加进主 `docker-compose.yml` 的 `include` 或 `extends`
  - 主机：`http://ragflow:9380`，API key 走 env `RAGFLOW_API_KEY`
- 新增 settings：`RAGFLOW_BASE_URL` / `RAGFLOW_API_KEY` / `ZHIPUAI_API_KEY` / `ZHIPUAI_EMBEDDING_MODEL` / `ZHIPUAI_RERANK_MODEL`
- `pyproject.toml` 加 `httpx`（已有）

docker 编排变更：
- 给 backend 容器加 `extra_hosts: ["ragflow:host.docker.internal"]` 或同网络
- 给 backend 容器加环境变量 `RAGFLOW_BASE_URL=http://ragflow:9380`

**验收**：脚本 `scripts/ragflow_smoke.py` 能创建 dataset、上传一个空 PDF、检索返回空、清理 dataset。

---

### 阶段 2：上传 + MinerU → RAGFlow ingest 管线

**目标**：用户在知识库页上传 PDF/Word/Excel，1-2 分钟内看到 chunk 列表。

前端：
- 新建 `app/knowledge/page.tsx`：KB 列表 + 详情（文档 / chunks 预览）
- 新建 `components/KbUploader.tsx`：拖拽上传 + 进度条（轮询 /api/kb/{id}/documents/{doc_id}/status）
- 新建 `components/ChunkPreview.tsx`：分页表格展示每页 chunk（page / bbox / snippet）

后端：
- `app/api/kb.py`：CRUD 知识库 + 上传 + 状态查询
- 新建 `app/workers/ingest_worker.py`：asyncio 后台 worker
  - 接收 doc_id → 从 attachments 表拿 storage_path → 调 MinerU（已有 `_resolve_mineru_url`） → 拿到 pages + bbox + blocks
  - 调 RAGFlow `/v1/document/upload`（dataset 已配置跳过 DeepDoc OCR，传 chunks）
  - 把 chunk 结果写 `kb_chunks` 表
  - 更新 `kb_documents.status = done / failed`
- 后端入口：上传完成后 `asyncio.create_task(ingest_worker.process(doc_id))` 异步触发

MinerU 集成：
- **不替换** MinerU；只是把 MinerU 输出转成 RAGFlow 期望的 chunk 格式
- 调研：RAGFlow dataset 支持 `parser_config` 自定义解析器 + `chunking_config`；或者直接调 `/v1/document/upload` 时传预解析的 `chunks` 字段（v0.27 文档）
- **PoC 验证**：手动构造一份 RAGFlow API 调用，验证能不能带 bbox chunk 上传

**验收**：上传 `System Test Report — Release 4.pdf` 5 秒内 status=parsing，30 秒内 status=done，chunks 列表显示带 bbox 数据。

---

### 阶段 3：bot 关联 KB + 检索 → prompt 注入

**目标**：bot 群聊发言前自动检索 KB 内容。

后端：
- 新建 `app/services/rag_retriever.py`：
  - `retrieve_for_bot(bot_id, query, top_k=5)` → 收集 bot 关联的 kb 列表，每个 kb 调 `ragflow_client.retrieval(query)`，合并去重按 score 排序
  - rerank：调智谱 GLM rerank API（`/api/paas/v4/rerank`）对 top-N 重排
- 修改 `app/orchestrator/msghub.py` `_generate_agent`：
  - 在构造 system prompt 前，调 `retrieve_for_bot(bot.id, user_prompt)` 拿 chunks
  - 把 chunks 注入到 `system_content`：
    ```
    【知识库参考】（请使用 [doc: filename p.X ¶Y] 标注你引用的每一条来源）
    [doc: filename.pdf p.3 ¶2] "..."
    [doc: filename.pdf p.5 ¶1] "..."
    ```
- 修改 prompt 结尾约束："如果使用了上面的参考资料，**每段引用必须带 [doc: filename p.X ¶Y] 标记**；若参考资料与问题无关，回答'暂未找到相关资料'"

数据库：
- `bot_kb(bot_id, kb_id)` 数据模型完成
- alembic 迁移 + backfill 给 `doc_writer` bot 默认挂载"项目模板" KB

**验收**：在 KB 上传一份 "财务报销制度.pdf"，`业务分析师` bot 提问"差旅费报销标准是什么" → 答案含 `[doc: 财务报销制度.pdf p.X ¶Y]` 标记。

---

### 阶段 4：前端引用渲染 + bbox 高亮

**目标**：点击答案中的引用，跳转 PDF 并框选原文区域。

前端：
- 引入 `pdfjs-dist` 包（懒加载，避免拖慢首屏）
- 新建 `components/PdfViewerWithBbox.tsx`：
  - 用 pdfjs-dist 渲染 PDF 到 canvas
  - 接 `bbox: [x1, y1, x2, y2]` + `page: number` props，画 SVG overlay 黄色半透明框
  - 接收 "go to page + bbox" 指令 → 跳页 + 高亮
- 新建 `components/SourceCitation.tsx`：
  - 解析 LLM 答案中的 `[doc: filename p.X ¶Y]` → 渲染成可点击 chip "📎 filename p.X"
  - 点击 → 调 `api.getChunkDetail(chunk_id)` 拿完整 bbox → 打开 `PdfViewerWithBbox`
- 修改 `app/knowledge/page.tsx` chunk 预览：每个 chunk 行加"👁 预览"按钮 → 打开 `PdfViewerWithBbox`
- 修改 `components/ChatBubble.tsx`：
  - bot bubble content 渲染时调用 `renderMessageWithCations`
  - 把每个 `[doc: ...]` 替换成 `<SourceCitation>` 组件

`lib/markdown.ts` 扩展：
- 加一个 token 类型 `citation`，解析 `[doc: filename p.X ¶Y]` → 返回 `{filename, page, para}` 结构
- 让 ChatBubble 用它生成 SourceCitation chips

**验收**：在答案里看到 `[doc: 财务报销制度.pdf p.3 ¶2]` 渲染成绿色 chip，点击 → 右侧抽屉打开 PDF 第 3 页，黄色框选定位的段落。

---

### 阶段 5：知识库管理 UI + 多 bot 关联 UI + 权限

**目标**：用户能自助上传、删除、预览、关联 bot。

前端：
- `app/knowledge/page.tsx`：KB 列表 + 创建/删除
- `app/knowledge/[id]/page.tsx`：KB 详情（文档列表 + 上传 + 检索测试）
- `app/bots/[id]/page.tsx`（或 `/bots` 现有页加 section）：bot 编辑表单新增 "知识库" tab，列出可关联的 KB，多选

后端：
- `app/api/kb.py`：增 / 删 / 改 / 列表
- `app/api/bots.py`：PATCH `/api/bots/{id}` 加 `kb_ids: list[int]` 字段，写 `bot_kb` 表
- 权限：
  - 公开 KB（`scope=public`）所有 bot 可挂
  - 用户私有 KB（`scope=user`）只有 owner + admin 可挂
  - bot_kb 写入时校验权限

**验收**：用户创建 KB "项目模板"，上传 5 份 PDF，关联给 `doc_writer` 和 `业务分析师` 两个 bot，群聊里两个 bot 都能引用这些 KB。

---

## 4. 关键文件 / 新增清单

### 后端新增
| 路径 | 用途 |
|---|---|
| `backend/app/services/ragflow_client.py` | RAGFlow HTTP API 客户端 |
| `backend/app/services/rag_retriever.py` | KB 检索 + rerank + 排序去重 |
| `backend/app/services/zhipuai_embed.py` | 智谱 embedding + rerank HTTP 调用（可复用模式） |
| `backend/app/workers/ingest_worker.py` | 后台 chunk 化 + 入 RAGFlow |
| `backend/app/api/kb.py` | KB + 文档 API |
| `backend/app/api/bots.py` | 增 `kb_ids` PATCH 字段 |
| `backend/alembic/versions/0011_knowledge_base.py` | 新表 |
| `infra/docker-compose.ragflow.yml` | RAGFlow 编排 |
| `scripts/ragflow_smoke.py` | 烟雾测试脚本 |

### 后端修改
- `backend/app/orchestrator/msghub.py`：`_generate_agent` 注入知识库上下文 + 引用标记约束
- `backend/app/api/chat.py`：暴露检索命中字段给前端（`cited_refs` SSE field）
- `backend/pyproject.toml`：加 `pdfjs-dist` 对应的 Python 依赖（若有，但 Python 端不需要，主要是前端）

### 前端新增
| 路径 | 用途 |
|---|---|
| `frontend/app/knowledge/page.tsx` | KB 列表 |
| `frontend/app/knowledge/[id]/page.tsx` | KB 详情 + 上传 + 检索测试 |
| `frontend/components/KbUploader.tsx` | 上传组件 |
| `frontend/components/ChunkPreview.tsx` | chunk 列表预览 |
| `frontend/components/PdfViewerWithBbox.tsx` | PDF.js 渲染 + bbox overlay |
| `frontend/components/SourceCitation.tsx` | `[doc: ...]` → 可点击 chip |
| `frontend/lib/ragflow.ts` | RAGFlow 后端 API wrapper |

### 前端修改
- `frontend/components/ChatBubble.tsx`：解析答案中的 `[doc: ...]` 标记
- `frontend/lib/markdown.ts`：新增 `citation` token 解析
- `frontend/components/Composer.tsx`：上传入口加 "添加到知识库" 选项
- `frontend/package.json`：`pdfjs-dist`

---

## 5. 数据契约

### 5.1 KB 检索上下文注入 prompt 格式
```
【知识库参考】（请使用 [doc: filename p.X ¶Y] 标注每条引用的来源）
[doc: System Test Report — Release 4.pdf p.3 ¶2]
"UAT 测试结果已达成所有退出标准..."

[doc: System Test Report — Release 4.pdf p.5 ¶1]
"测试覆盖率达 96%，Sev-1/Sev-2 缺陷清零..."
```

### 5.2 答案引用标记格式
LLM 返回内容中嵌入：
```
根据 [doc: System Test Report — Release 4.pdf p.3 ¶2]，UAT 测试已达成
所有退出标准；同时 [doc: System Test Report — Release 4.pdf p.5 ¶1]
显示覆盖率 96%。
```

### 5.3 SSE 事件新增 `cited_refs`
```json
{
  "type": "message_end",
  "bot_id": 19,
  "bot_name": "专业写文档",
  "content": "...根据 [doc: 财务报销制度.pdf p.3 ¶2]...",
  "cited_refs": [
    {"filename": "财务报销制度.pdf", "page": 3, "para": 2, "chunk_id": 142, "bbox": [120, 230, 480, 310], "score": 0.92}
  ]
}
```

前端用 `cited_refs` 渲染 chip 列表 + 点击触发 PDF viewer 跳转。

---

## 6. RAG 引擎配置（RAGFlow dataset）

```json
{
  "name": "项目模板",
  "parser_config": {
    "chunk_method": "custom",   // 由我们喂入 MinerU 解析好的 chunks
    "delimiter": null
  },
  "embedding_config": {
    "provider": "zhipuai",
    "model": "embedding-2",
    "base_url": "https://open.bigmodel.cn/api/paas/v4"
  },
  "rerank_config": {
    "provider": "zhipuai",
    "model": "rerank",
    "base_url": "https://open.bigmodel.cn/api/paas/v4"
  }
}
```

---

## 7. 风险与决策记录

| 风险 | 缓解 |
|---|---|
| RAGFlow 部署重（≥6 容器、4C16G50GB + GPU 推荐） | 阶段 1 先用 CPU 版起步；MinerU 跑在 host；预算不足时退回 Haystack 自建方案 |
| RAGFlow 项目 2026 Q2 起 Go 重写，部分 Python 文档过时 | 以官方 API 文档为准，HTTP 调用层在 `ragflow_client.py` 单一文件封装 |
| 智谱 GLM rerank 上线时间 / 配额不确定 | slot 已预留，rerank 失败时降级到 "embedding 相似度排序" |
| LLM 不严格遵守 `[doc: ...]` 标记 | prompt 强约束 + system prompt 末尾"如果不引用资料则直接说'暂未找到'" + 后端 regex 校验（如缺失就 strip） |
| MinerU 输出格式与 RAGFlow chunk schema 不完全匹配 | 阶段 2 PoC 验证；若不匹配，转用 Haystack 自建方案（plan 仍保留此 fallback） |
| 多 bot 同名 KB 互相覆盖 | bot_kb 多对多；检索时按 bot_id 隔离 + admin 可设 KB `is_public=true` 全局共享 |

---

## 8. 关键决策记录（已通过 AskUserQuestion 确认）

| 决策点 | 选定 |
|---|---|
| RAG 框架 | **RAGFlow** (Apache 2.0) |
| 前端 PDF 查看器 | **PDF.js (Mozilla)** |
| rerank 现阶段 | **GLM 自带 rerank**（预留 BaseRanker slot） |
| Embedding | **智谱 GLM embedding-2 / embedding-3**（已确定） |
| OCR | **沿用 MinerU**（不替换） |

---

## 9. 验收里程碑

| 阶段 | 验收标志 | ETA |
|---|---|---|
| 1 | RAGFlow 容器起来 + smoke 脚本通过 | 1 周 |
| 2 | 用户上传 PDF 30 秒内看到 chunks | 1 周 |
| 3 | bot 发言答案含 `[doc: ...]` 引用 | 1 周 |
| 4 | 点击引用跳转 PDF bbox 高亮 | 1 周 |
| 5 | KB 管理 UI + 多 bot 关联 + 权限 | 1 周 |

总计：~5 周，最小可用版本（阶段 1-3）可 2-3 周内交付。

---

## 10. 调研原文索引

详见 `.trae/documents/rag_research.md`（如生成）。本计划仅取结论。