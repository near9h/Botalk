# backend/app/workers

> 后台 worker（解析、上传等长任务）。当前为**同步阻塞**模式（上传时启动后台 asyncio 任务），后续可换 Celery / RQ。

## 文件

- `ingest_worker.py` — KB 文档 ingest（下载文件 → MinerU 解析 → chunks 落库 → embedding）

## 任务流

```
attach row created (status=pending)
  → ingest_worker kicks (asyncio.create_task)
  → kb_documents.status = parsing
  → 调用 services/mineru.py 解析（PDF）或 services/office_pdf.py 转 PDF 后再解析
  → chunks 入 kb_chunks
  → 调用 services/zhipuai_embed.py 生成 embedding（可选 backfill）
  → kb_documents.status = ready / failed
```

## 失败处理

- 任一步抛异常 → `kb_documents.error` 写错误
- 前端轮询 `GET /api/kb/{kb_id}/documents/{doc_id}` 看 status