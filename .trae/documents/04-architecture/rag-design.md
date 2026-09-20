# KB 检索设计（pgvector + 智谱 GLM embedding）

> 当前活跃设计。**不再使用 RAGFlow**（详见 [ADR-0004](../adr/0004-kb-local-rag.md)）。
> 历史 RAGFlow 方案归档于 [`../history/rag-design.md`](../history/rag-design.md)（不再维护）。

---

## 1. 一句话

知识库 = Postgres 里的几张表 + pgvector 向量列 + 智谱 GLM embedding API。**零额外容器**。

## 2. 数据模型

| 表 | 关键列 |
| --- | --- |
| `knowledge_bases` | `id / public_id / name / scope / is_public / owner_id` |
| `attachments` | 通用附件（KB 与 chat 共用，group_id=NULL 区分） |
| `kb_documents` | `id / kb_id / attachment_id / status(pending/parsing/ready/failed) / chunk_count / error` |
| `kb_chunks` | `id / kb_doc_id / page / para / bbox_json / snippet / embedding(vector) / embedding_model` |

> `ragflow_dataset_id` 列仍在 schema 里（向后兼容），但**永远不写入新值**。

## 3. Pipeline

### 3.1 Ingest（上传 → ready）

```
POST /api/kb/{kb_id}/documents  (multipart)
  │
  ▼
backend/app/api/kb.py
  ├─ mime + size 校验
  ├─ 写文件到 data/uploads/
  ├─ attachments / kb_documents 行（status=pending）
  └─ asyncio.create_task(ingest_worker.run)

backend/app/workers/ingest_worker.py
  ├─ status → parsing
  ├─ mime 分支：
  │    ├─ pdf  → services/mineru.py      → 文本 + bbox
  │    └─ office（docx/xlsx/pptx）
  │             → services/office_pdf.py  → PDF（LibreOffice headless）
  │             → services/mineru.py
  ├─ 分块 → kb_chunks 写 N 行（含 bbox_json + snippet）
  ├─ services/zhipuai_embed.py → embedding 写回 kb_chunks.embedding
  ├─ status → ready
  └─ audit_log("kb.doc.ingested")

失败：
  status → failed + kb_documents.error 写错误
```

### 3.2 Retrieve（查询 → 引用）

```
msghub._generate_agent(prompt, bot_id, kb_ids)
  │
  ▼
backend/app/services/rag_retriever.retrieve_for_bot(bot_id, query, session)
  │
  ▼
backend/app/services/local_retriever.retrieve(bot_id, query, session, top_k=N)
  │
  ├─ BM25 over kb_chunks.snippet        (兜底)
  ├─ pgvector cosine over kb_chunks.embedding  (主召回)
  ├─ RRF 融合
  └─ 返回 top-N [{chunk_id, snippet, page, para, bbox, score, ...}]
  │
  ▼
RetrievalResult → msghub 拼成 system prompt 的 "参考资料 [n] ..." 块
  │
  ▼
LLM 输出含 [n] → 前端替换为 @@CITATION_n@@
  │
  ▼
点击 chip → /api/kb/{kb_id}/chunks/{chunk_id} → bbox + snippet → PDF.js 跳页 + 红框
```

## 4. 关键代码

| 模块 | 作用 |
| --- | --- |
| `backend/app/services/local_retriever.py` | BM25 + pgvector + RRF 融合（**唯一**检索路径） |
| `backend/app/services/rag_retriever.py` | 上层封装，bot→kb 列表→统一返回 `RetrievalResult` |
| `backend/app/services/zhipuai_embed.py` | 智谱 GLM embedding API 包装 |
| `backend/app/services/ragflow_client.py` | **兼容 stub**（`is_configured()` 永远 `False`） |
| `backend/app/workers/ingest_worker.py` | 后台 ingest 任务（解析 + 分块 + embedding） |
| `backend/app/services/mineru.py` | MinerU 解析 PDF |
| `backend/app/services/office_pdf.py` | LibreOffice headless 转 PDF |
| `scripts/backfill_chunk_embeddings.py` | 旧 KB 补 embedding |

## 5. 失败 / 降级

| 场景 | 行为 |
| --- | --- |
| 智谱 API 429 | 重试 3 次；仍失败则本次 chat 走"无 KB 引用"路径（不报错） |
| 智谱 API 未配（`ZHIPUAI_API_KEY` 缺失） | `local_retriever.is_configured()` 返回 `False`，检索整体跳过 |
| 文档解析超时 | `kb_documents.status=failed` + `error` 写超时秒数 |
| Embedding 模型变更 | `embedding_model` 列记录；读取时按模型分组 |

## 6. 相关

- ADR-0004 — 决策记录（pgvector + 智谱 GLM）
- [hybrid-bm25-rag.md](hybrid-bm25-rag.md) — BM25 + pgvector 融合细节
- [sentence-window-context.md](sentence-window-context.md) — 上下文窗口扩展
- [04-architecture/data-flow.md § F3 F4](data-flow.md) — 上传 / 检索时序
- [06-implementation/citation-stability.md](../06-implementation/citation-stability.md) — 引用稳定实现