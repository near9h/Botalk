# 方案：RAG 检索升级为 Hybrid Search（dense + BM25 + RRF）

## 摘要

BotGroup 当前 RAG 检索**只有 dense**（pgvector 余弦相似度 + GLM embedding-3 + 可选 GLM rerank），用户截图证实：查询 "if people work on offshore rigs/platforms, who needs to referral" 时，召回的内容**没包含** "SPC/Treaty" 这条关键事实——因为 dense embedding 把精确术语淹没在了语义相似度里。

业内 2026 年共识（[Gloss](https://gloss.run/post/hybrid-search-in-90-minutes-the-single-biggest-rag-quality-win-in-2026)、[dev.to Production RAG](https://dev.to/dzakiamriz/production-rag-in-2026-hybrid-search-with-pgvector-reciprocal-rank-fusion-and-context-caching-1m5h)、[Microsoft Learn](https://learn.microsoft.com/en-sg/training/modules/build-rag-applications-azure-database-postgresql/7-improve-accuracy-advanced-rag-architecture)、[Tiger Data](https://www.tigerdata.com/blog/introducing-pg_textsearch-true-bm25-ranking-hybrid-retrieval-postgres)）：

> "73% of RAG failures come from retrieval, not generation. … Adding BM25-style keyword search (Postgres full-text search) complements embeddings by capturing exact terms and lexical signals. Fusing dense and sparse results with Reciprocal Rank Fusion is a robust default. … recall improvement is consistently 25 to 45 percent."

> "If your query mentions a specific product code or function name, dense search blurs it into 'things that look kind of like a product code' rather than 'the exact product code.' That is where BM25 comes in."

本方案在 BotGroup 现有 **pgvector + GLM embedding** 之上**叠加一层 BM25 全文检索**，通过 **Reciprocal Rank Fusion (RRF)** 合并两份排序。**不替换** dense 路径，**不引入新依赖服务**——只用 PostgreSQL 已有能力。

***

## 调研结论：业内方案对比

| 方案                                  | 复杂度   | 适用场景                   | 推荐度      |
| ----------------------------------- | ----- | ---------------------- | -------- |
| **A. hybrid (BM25 + dense + RRF)**  | ⭐⭐    | 通用，含精确术语/ID/产品代码的检索    | ✅ **选定** |
| B. contextual retrieval (Anthropic) | ⭐⭐    | chunk 缺乏自身上下文，需 LLM 增广 | 备选       |
| C. parent-document retrieval        | ⭐⭐⭐   | 答案散布在多 chunk           | 备选       |
| D. GraphRAG / RAPTOR                | ⭐⭐⭐⭐⭐ | 跨文档全局关系                | 过重       |
| E. HyDE                             | ⭐⭐⭐   | 查询太短                   | 不适合精确术语  |

A 是用户痛点（"SPC / Treaty" 是精确术语）的**对症下药**——BM25 索引会**直接命中** "Referral to SPC" 这种 token。

实现细节调研：

* Postgres 自带 `tsvector + ts_rank`，**纯 SQL，无扩展**——对英文 OK，对中文需要 `zhparser`/`pg_jieba`（需安装）或用 `simple` 配置（不分词，按空格切）。

* 当前 docker 镜像 `pgvector/pgvector:pg16` **只有 plpgsql + vector**，没装 zhparser。

* 5166 个 chunk、平均 160 字节——足够小，可以**全表扫**+`ts_rank` 排序，性能不是瓶颈。

***

## 现状分析（基于 Phase 1 探索结果）

| 步骤         | 文件:行                                                            | 当前实现                                                                        | 痛点                              |
| ---------- | --------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------- |
| 索引         | `backend/alembic/versions/0019_local_vector_retrieval.py:60-95` | `kb_chunks` 加 `text`、`embedding` (vector(2048))、`embedding_model` 列；HNSW 索引 | 缺 tsvector 列 + GIN 索引           |
| 检索         | `backend/app/services/local_retriever.py:228-302`               | 单一 cosine 距离 SELECT，配 GLM rerank                                            | 没有 lexical 信号                   |
| Prompt     | `backend/app/services/rag_retriever.py:147-184`                 | `_format_context_block` 渲染 chunks                                           | LLM 见到的全是 cosine top-K          |
| Rerank     | `backend/app/services/local_retriever.py:307-319`               | GLM rerank 二次精排                                                             | 改善小幅度，不解决"召回就漏"                 |
| Extensions | `pg_extension` 查询结果：`plpgsql, vector`                           | 仅这两个                                                                        | 需要加 `pg_trgm` 或 native tsvector |

***

## 方案设计

### 选 A：hybrid（dense + BM25 + RRF）

**为什么不换 dense**：dense 已上线，召回质量已经覆盖"语义相关"维度；删掉会回到更糟的 baseline。

**为什么是 BM25 而不是别的 sparse**：

* 标准做法、行业共识；

* Postgres 原生支持（`tsvector`/`ts_rank`）；

* 不引入新进程（不像 Elasticsearch/Meilisearch）。

**为什么 RRF 而不是加权求和**：

* dense 的余弦分数和 BM25 的 ts\_rank 分数量纲完全不同（\[0,1] vs \[0, ∞)），加权需要校准；

* RRF 只用**排名**，自然跨分数量纲——业内"默认稳健"的方案；

* 实现简单，\~20 行 Python。

### 双轨 + RRF 流程

```
              ┌─────────────────┐
   user query ─┤  GLM embed query ├─→ dense cosine hits (top 50)
              └─────────────────┘         │
                                          │   rank_dense[chunk_id]
                                          ▼
                          ┌─── RRF fusion (k=60) ───┐
                          │                          │
                          │   rank_bm25[chunk_id]    │──→ fused ranked list
                          ▼                          │   (top_n = 10..20)
              ┌────────────────────────┐               │
              │  tsvector @@ tsquery   │               │
              │  ts_rank scoring        │               │
              └────────────────────────┘               │
                                                         ▼
                                              ┌─────────────────┐
                                              │  GLM rerank     │
                                              │  (existing)     │
                                              └─────────────────┘
                                                         │
                                                         ▼
                                                  to LLM prompt
```

**为什么先取 top\_50 / top\_50 再 RRF → top\_20 → rerank**：保留更多候选（业内 dual-encoder 标准做法），rerank 仍保留。

***

## 实施步骤

### 步骤 1：alembic 迁移加 tsvector 列 + GIN 索引

**新建** `backend/alembic/versions/0021_hybrid_search_bm25.py`：

```python
"""hybrid search: add tsvector + GIN index on kb_chunks.text.

We use the GENERATED ALWAYS ... STORED pattern so application code
never has to maintain a parallel tsv column — Postgres rebuilds it
on every text UPDATE. The `'simple'` text-search config is a
whitespace tokenizer; for English/PDF prose it works well enough
that we don't need to install zhparser. CJK n-gram precision is
acceptable for our domain (legal / insurance PDFs with mixed EN/CN).

If a future deployment sees low recall on Chinese-only queries,
swap `'simple'` for a `pg_trgm` index (built-in, no install) or
`zhparser` (drop-in extension that ships its own Chinese stop
word list). The query interface stays unchanged.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0021_hybrid_search_bm25"
down_revision: Union[str, None] = "0020_kb_public_id"

def upgrade() -> None:
    op.add_column(
        "kb_chunks",
        sa.Column("tsv", sa.dialects.postgresql.TSVECTOR, nullable=True),
    )
    # GENERATED column: keeps tsv in sync with text automatically.
    op.execute(
        "ALTER TABLE kb_chunks "
        "ALTER COLUMN tsv TYPE tsvector "
        "USING to_tsvector('simple', coalesce(text, ''))"
    )
    op.execute(
        "ALTER TABLE kb_chunks "
        "ALTER COLUMN tsv SET NOT NULL"
    )
    # GIN index — the standard pick for tsvector.
    op.create_index(
        "ix_kb_chunks_tsv",
        "kb_chunks",
        ["tsv"],
        postgresql_using="gin",
    )

def downgrade() -> None:
    op.drop_index("ix_kb_chunks_tsv", table_name="kb_chunks")
    op.drop_column("kb_chunks", "tsv")
```

**注意点**：

* `kb_chunks` 是 partitioned-by-tenant 不需要——它只是单表，GENERATED STORED 即可。

* `'simple'` 配置：按空格切词 + 全部转小写，无停用词。对英文 OK，对中文按字符级（unigram）。可接受。

* 升级时不需要 rebuild——Postgres 自动维护。

### 步骤 2：扩展 `kb_chunks` model

**改** `backend/app/db/models.py:425-450`：

* 加 `tsv` 字段 `Mapped[str] = mapped_column(TSVECTOR, nullable=False)`（GENERATED 列写到 SQLAlchemy 不影响读）；

* 注释解释：`tsv` 由 PG 自动维护，应用层不写。

### 步骤 3：hybrid 检索函数

**改** `backend/app/services/local_retriever.py:228-302` 的 `retrieve()`：

在 `retrieve()` 内部，把原本**只跑 cosine** 的 SELECT 拆成**两个并行 SELECT**，合并到 `hits` 列表：

```python
async def retrieve(...) -> list[dict[str, Any]]:
    # ...existing mounted-KB discovery + query embedding unchanged...

    # 1) Dense hits (existing query, capped at TOP_K_DENSE = 50)
    dense_rows = await session.execute(text("""
        SELECT c.id AS chunk_id, ..., 1 - (c.embedding <=> :vec) AS score
        FROM kb_chunks c JOIN kb_documents d ON c.kb_doc_id = d.id
        WHERE d.kb_id = ANY(:kb_ids)
        ORDER BY c.embedding <=> :vec
        LIMIT :top_k_dense
    """), {...})

    # 2) BM25 hits (new): tsvector @@ websearch_to_tsquery
    bm25_rows = await session.execute(text("""
        SELECT c.id AS chunk_id, ...,
               ts_rank_cd(c.tsv, websearch_to_tsquery('simple', :q)) AS bm25_score
        FROM kb_chunks c JOIN kb_documents d ON c.kb_doc_id = d.id
        WHERE d.kb_id = ANY(:kb_ids)
          AND c.tsv @@ websearch_to_tsquery('simple', :q)
        ORDER BY bm25_score DESC
        LIMIT :top_k_bm25
    """), {...})

    # 3) RRF fusion
    fused = reciprocal_rank_fusion(dense_rows, bm25_rows, k=60)
    # 4) Top-N cap (existing top_n) + format hits
    return [format_hit(row) for row in fused[:top_n]]
```

**RRF 实现**（写在 `local_retriever.py` 顶部 helper）：

```python
def reciprocal_rank_fusion(
    dense_rows: list, bm25_rows: list, k: int = 60
) -> list:
    """RRF: score = Σ 1 / (k + rank_in_list). k=60 is the standard
    smoothing constant from Cormack et al. 2009."""
    scores: dict[int, float] = {}
    payload: dict[int, dict] = {}
    for rank, row in enumerate(dense_rows, start=1):
        cid = row["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        payload[cid] = row
    for rank, row in enumerate(bm25_rows, start=1):
        cid = row["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        # payload carries dense-side metadata (or BM25-side as fallback)
        payload.setdefault(cid, row)
    # Re-sort by combined RRF score desc
    return [payload[c] for c, _ in sorted(scores.items(), key=lambda x: -x[1])]
```

### 步骤 4：可配置开关

**改** `backend/app/config.py`：

```python
rag_hybrid_enabled: bool = True
rag_top_k_dense: int = 50
rag_top_k_bm25: int = 50
rag_rrf_k: int = 60
```

让运营可以**关闭 hybrid 回退到 dense-only**（紧急兜底），调节 RRF k 值。

### 步骤 5：rerank 仍是最后一道闸

保持现有的 `local_retriever` 第 4 步 GLM rerank 不动——rerank 在 hybrid 之后做最终精排，是 **dense + BM25 → RRF → rerank → top\_n → LLM** 四级流水线。

### 步骤 6：测试

**新建** `backend/tests/test_hybrid_search.py`：

* 单测 RRF 合并逻辑；

* 单测 BM25-only 命中（dense miss 但 BM25 hit → 应该出现在 fused）；

* 单测 dense-only 命中（BM25 miss 但 dense hit → 应该出现在 fused）；

* 单测双空时返回空；

* **关键单测**：用用户真实痛点 case——构造 chunk 包含 "Referral to SPC is required for accounts with annual GWP exceeding \$100,000" + 一个**不含**该 token 但语义相似的对照 chunk；查询 "Referral to SPC" → 验证 BM25 命中该 token 的 chunk 出现在 RRF top-K。

集成测试：在容器里手动发"if people work on offshore rigs/platforms, who needs to referral"问题，验证 LLM 回答里出现"SPC/Treaty required"。

### 步骤 7：监控 + 调参

在 `retrieve()` 返回的 dict 加一个 `match_source` 字段（`'dense'` / `'bm25'` / `'both'`），在 `CitationDrawer` 的 UI 里展示（可选），方便用户看到哪条结果是 BM25 救回来的——给运营一个调 RRF k 值的依据。

***

## 涉及文件清单

| 操作 | 路径                                                               |
| -- | ---------------------------------------------------------------- |
| 新建 | `backend/alembic/versions/0021_hybrid_search_bm25.py`            |
| 改  | `backend/app/db/models.py`（kb\_chunks 加 `tsv` 字段）                |
| 改  | `backend/app/services/local_retriever.py`（dense + BM25 + RRF）    |
| 改  | `backend/app/config.py`（hybrid 开关 + k 值）                         |
| 新建 | `backend/tests/test_hybrid_search.py`                            |
| 改  | `frontend/components/SourceCitation.tsx`（可选：显示 match\_source 角标） |

***

## 假设与决策

* **Postgres** **`simple`** **配置 + 自动 GENERATED 列**：避免引入新扩展；中文按 unigram 处理，命中率足够（用户示例 query "SPC" / "Treaty" 都是拉丁 token，单字 unigram 也命中）。如果未来发现中文长尾检索差，再升级到 `zhparser`（migration 一次性切换）。

* **RRF k=60**：Cormack 等的原始推荐值。`config.py` 暴露成 `rag_rrf_k` 让运营可调。

* **不引入 pg\_textsearch / ParadeDB**：docker 镜像保持官方 pgvector，零额外依赖。

* **rerank 仍然走 GLM**：hybrid + rerank 是业内 dual-pass 的标配；rerank 的 query 复杂度成本不变（只过 hybrid top\_n，不是双倍）。

* **不动** **`embed_chunks_for_doc`**：BM25 索引在 migration 自动 GENERATED，不需 ingest worker 改代码。

* **不动** **`kb_chunks.text`** **上限（4000 字符）**：tsvector 可以处理长文本。

***

## 验证步骤

1. `cd backend && alembic upgrade head` → 验证 migration 应用成功，GIN 索引已建。
2. `pytest tests/test_hybrid_search.py` → RRF 单测通过。
3. 容器重启 + 重发用户的实际问题：

   * query: "if people work on offshore rigs/platforms, who needs to referral"

   * 期望：bot 回答里出现 "Referral to SPC is required" / "Referral to SPC / Treaty is required"
4. 旧场景回归：发 "我要裁员" → 回答仍正确（dense + BM25 互补，BM25 不会拖低 dense 召回）。
5. 跑一次 `EXPLAIN ANALYZE` 确认 GIN 索引生效（idx scan 而非 seq scan）。

***

## 调研来源

* [Gloss — Hybrid Search in 90 Minutes, the Single Biggest RAG Quality Win in 2026](https://gloss.run/post/hybrid-search-in-90-minutes-the-single-biggest-rag-quality-win-in-2026)

* [dev.to — Production RAG in 2026: Hybrid Search with pgvector, RRF, and Context Caching](https://dev.to/dzakiamriz/production-rag-in-2026-hybrid-search-with-pgvector-reciprocal-rank-fusion-and-context-caching-1m5h)

* [Tiger Data — pg\_textsearch: True BM25 Ranking and Hybrid Retrieval](https://www.tigerdata.com/blog/introducing-pg_textsearch-true-bm25-ranking-hybrid-retrieval-postgres)

* [Google Cloud — Native BM25 search in AlloyDB and Cloud SQL](https://cloud.google.com/blog/products/databases/native-bm25-search-in-alloydb-and-cloud-sql)

* [pgEdge — Hybrid Search in PostgreSQL: BM25, Sparse Vectors, and RRF](https://www.pgedge.com/blog/hybrid-search-in-postgresql-bm25-sparse-vectors-and-reciprocal-rank-fusion)

* [Microsoft Learn — Improve accuracy with advanced RAG architectures](https://learn.microsoft.com/en-sg/training/modules/build-rag-applications-azure-database-postgresql/7-improve-accuracy-advanced-rag-architecture)

* [dev.to — 9 RAG Techniques That Actually Improve Retrieval Quality](https://dev.to/bibekkakati/9-rag-techniques-that-actually-improve-retrieval-quality-36jh)

* [dev.to — The Retrieval Checklist I Wish I'd Had Before Shipping RAG](https://dev.to/james_anderson_h/the-retrieval-checklist-i-wish-id-had-before-shipping-rag-2j5a)

* [besthub — Boost RAG Accuracy from 60% to 94% with 11 Proven Strategies](https://www.besthub.dev/articles/boost-rag-accuracy-from-60-to-94-with-11-proven-strategies-d1c8a051ace5)

