# ADR-0004: KB 默认本地 BM25+向量，可选 RAGFlow

- **状态**：Accepted
- **日期**：2026-09-19
- **决策者**：架构组

## 背景

知识库检索有几种实现路径。

## 选项

| 选项 | 优劣 |
| --- | --- |
| RAGFlow 一站式 | ✅ 功能多；❌ 部署重；❌ 引用 snippet 受限于其 API |
| 本地 BM25 + 向量 | ✅ 部署轻（pgvector）；✅ snippet 自由可控；❌ 检索质量需调 |
| Hybrid（默认本地 + 可选 RAGFlow） | ✅ 部署灵活；✅ 上层抽象统一；❌ 双路径维护 |

## 决策

**Hybrid**：默认本地（`local_retriever.py`），如环境变量 `RAGFLOW_*` 配齐则走 RAGFlow（`rag_retriever.py` 兜底）。

理由：

1. 单机部署优先 → 本地不引入额外容器
2. snippet / bbox 对齐是核心用户体验（看 [06-implementation/citation-stability.md](../06-implementation/citation-stability.md)），自研可控
3. RAGFlow 在大语料 / 复杂 query 场景更稳，作为可选升级路径

## 后果

- ✅ 默认零依赖启动
- ✅ snippet/bbox 完全可控
- ✅ 上层调用接口统一
- ⚠️ 本地检索需要 backfill chunk embeddings（看 `scripts/backfill_chunk_embeddings.py`）

## 相关

- `backend/app/services/local_retriever.py` — BM25 + 向量
- `backend/app/services/rag_retriever.py` — 主入口（融合）
- [06-implementation/citation-stability.md](../06-implementation/citation-stability.md)