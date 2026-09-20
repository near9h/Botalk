# ADR-0004: KB 检索 = pgvector + 智谱 GLM embedding（不再引入 RAGFlow）

- **状态**：Accepted
- **日期**：2026-09-19（v1） / 2026-09-20（修订：明确放弃 RAGFlow 路径）
- **决策者**：架构组

## 背景

知识库检索有过几个备选路径，2026-09 早期一度决定走 RAGFlow（详见 `history/rag-design.md`），后续因为部署重、snippet 受限于其 API 等原因改回自建。

## 选项

| 选项 | 优劣 |
| --- | --- |
| RAGFlow 一站式 | ❌ 部署重（4 容器：server + mysql + es + minio）；❌ snippet/bbox 对齐受限；❌ 升级成本高 |
| 自建 pgvector + 智谱 GLM embedding + 简单 BM25 兜底 | ✅ 单容器（pgvector 已在 Postgres 里）；✅ snippet/bbox 完全可控；✅ 与现有 PDF.js viewer 无缝；⚠️ 大语料下需要 backfill |

## 决策

**只用 pgvector + 智谱 GLM embedding**。`backend/app/services/local_retriever.py` 是唯一检索路径。

`backend/app/services/ragflow_client.py` **保留为向后兼容 stub**（`is_configured()` 永远返回 `False`），理由：

1. 历史 KB 行可能仍带 `ragflow_dataset_id` 列，不能直接删表
2. 审计日志里历史 action 字符串含 "ragflow"，不能改
3. 旧 import 路径如果删了会触发 cpython 缓存失效

**任何新代码都不应再 `import ragflow_client` 做实际调用**；如确需检索路径，看 `local_retriever`。

## 后果

- ✅ 单依赖（pgvector + 智谱 API），零额外容器
- ✅ snippet / bbox 完全自控
- ✅ ingest / retrieval 在同一 Postgres 事务里，更易做审计
- ⚠️ 智谱 API 限速：要做好 429 重试
- ⚠️ 大语料：当前 top_k=5；后续如需召回更多，先扩 embedding 维度

## 旧 RAGFlow 时代的方案

归档于 [`../history/rag-design.md`](../history/rag-design.md)（不再维护）。

## 相关

- `backend/app/services/local_retriever.py` — BM25 + pgvector + RRF 融合
- `backend/app/services/rag_retriever.py` — 上层封装（pipeline 注释写得很清）
- `backend/app/services/ragflow_client.py` — 兼容 stub（永远返回 `False`）
- `backend/app/services/zhipuai_embed.py` — 智谱 GLM embedding
- [04-architecture/rag-design.md](../04-architecture/rag-design.md) — 当前活跃设计