# 方案：Sentence-Window Retrieval — 召回后拼接相邻 chunk 给 LLM

## 摘要

Hybrid (dense + BM25 + RRF) 已经把 `Referral to SPC / Treaty` 这条精确术语的 chunk 召回到 top-N（前面已用 SQL 直查验证）。但 LLM 在回答时**没把精确术语写进正文**——只写了笼统结论 "mandatory referral trigger"。

根因：MinerU 把 PDF 按**段落级 block** 切，**单个 chunk 缺上下文**。`p.27 ¶3` 里"SPC/Treaty is required"前面那一段才解释"SPC 是谁、什么场景适用"——LLM 只看到孤立一句，不敢把"SPC/Treaty"作为答案写出。

业内对策是 **"search small, return big"**（[LangChain ParentDocumentRetriever](https://python.langchain.com/docs/modules/data_connection/retrievers/parent_document_retriever)、[ai-tldr.dev Parent Document Retrieval](https://ai-tldr.dev/learn/rag/advanced-rag/parent-document-retrieval/)）。对 BotGroup 来说，**MinerU 已经按 block 切好**，最轻量的版本是 **Sentence-Window**：召回命中一个 chunk 时，**把它在同页内的前后 N 个 block 一起拼上**。

业内把这个变体叫 **sentence-window retrieval**（ai-tldr.dev 原话）：
> "Common variant is sentence-window retrieval. You look up the index card (small), and it points you to the page that contains it (large)."

实现变更：
1. `kb_chunks` 表加一列 `block_seq`：同页内 block 的连续序号（用于 window 查询）。
2. 召回命中后，多发一条 SQL：**同 `kb_doc_id + page + block_seq ∈ [hit_seq - W, hit_seq + W]`** 的所有 chunk 拿出来，按 `block_seq` 排序拼接。
3. `kb_chunks.content` 拼接：`"… [prev_block]\n\n[middle_block]\n\n[next_block]…"`——**保留原 bbox 给 `[N]` chip**（中间那个），上下文的 chunk 不产生新引用。
4. 新增 `settings.rag_window_size = 1`（前后各 1 个 block）；0 表示关闭，回到无 window 的旧行为。

---

## 调研结论：业内方案对比

| 方案 | 复杂度 | 适用场景 | 推荐度 |
|------|--------|---------|--------|
| **A. Sentence-Window（邻接拼接）** | ⭐ | PDF/合同/法律文档按段落切过 | ✅ **选定** |
| B. Parent-Document（双层切分） | ⭐⭐⭐ | 通用，需要 200/2000 双索引 | 备选 |
| C. Contextual Retrieval（Anthropic 风格） | ⭐⭐⭐⭐ | 任何文档，需要重 embed | 过重 |
| D. Sentence-Window + Parent 混合 | ⭐⭐⭐⭐ | 多层级文档 | 备选 |

BotGroup 的现状是 A：MinerU 已经按段落切了 chunk，再做 B/C 是返工。所以选 A。

---

## 现状分析

| 步骤 | 文件:行 | 当前实现 |
|------|--------|---------|
| 检索 | `backend/app/services/local_retriever.py:192-401` | 召回 top_n chunk 直接给 LLM，**不带任何邻接 chunk** |
| Chunk metadata | `backend/app/db/models.py:425-456` | `kb_chunks` 有 `id`, `kb_doc_id`, `page`, `para`(=block_id)，**无连续 block_seq** |
| Ingest | `backend/app/workers/ingest_worker.py:254-282, 351-397` | `_markdown_chunks` / `_store_chunks` 落库时只存 `para=block_id` |
| Embed | `backend/app/services/local_retriever.py:embed_chunks_for_doc` | 一次 batch embedding；window 拼接不需重 embed |

MinerU `layout.json` 给的是 per-page block list（`_layout_to_chunks` line 288-318），每个 block 内部**没有天然序号**——但我们在 ingest 阶段已经按 `_layout_to_chunks` 遍历顺序给 `para=block_id`，这个 block_id 就是同页连续序号。**所以 `para` 直接就能当作 `block_seq`**——无需 schema 迁移，只需要新增读取逻辑。

---

## 方案设计

### 选 A：Sentence-Window（邻接拼接）

**为什么不是 B (Parent-Document)**：
- BotGroup 的 chunk 已经是 paragraph 级（~160 字节平均），足够小，**已经走 search-small**；问题在 generation-side 看不到上下文。
- 重新设计 child/parent 双层索引需要重建全部 chunk —— 现有 5166 条全部要重切、重 embed。
- Sentence-Window 是 B 的**最小可行版本**。

**为什么不是 C (Contextual Retrieval)**：
- 需要每个 chunk 跑一次 LLM 生成 context——5166 个 chunk × 一次 LLM = 一次性的大开销 + 后续每个新文档都要付。
- 而我们的 corpus 是相对结构化的法律/保险文档，**邻接 chunk 已经足够给 LLM 上下文**。

**怎么实现邻接**：
- 命中 `p.27 ¶3` chunk → 同 `kb_doc_id` 同 `page` 的 `para ∈ [3-1, 3+1]` = `[2, 3, 4]` → SQL `WHERE kb_doc_id=? AND page=? AND para BETWEEN ? AND ?`
- 按 `para ASC` 排序，把三个 chunk 的 `text` 用 `\n\n` 拼接
- **bbox 仍只用中间那个**（line 296 `c.bbox`），所以 PDF 高亮不会跑偏

### 数据流

```
retrieve(bot_id, query) 之前:
  hits = [chunk_a, chunk_b, chunk_c]   (RRF 排序)

retrieve 现在加 step 6.5:
  for hit in hits:
    siblings = SELECT * FROM kb_chunks
                WHERE kb_doc_id = hit.kb_doc_id
                  AND page = hit.page
                  AND para BETWEEN hit.para - W AND hit.para + W
                ORDER BY para
    merged_text = "\n\n".join(s.text for s in siblings)
    hit["content"] = merged_text   # 替换 LLM 看到的正文
    hit["window_size"] = len(siblings)
  return hits
```

中间 chunk 的 `bbox` / `citation_key` 不变；上下文的 chunk **不**产生新的引用 chip（避免 [1][2][3][4][6] 噪音）。

---

## 实施步骤

### 步骤 0：alembic 准备（**不动 schema**，但要 backfill）

不需要新列——直接复用 `para` 字段作为 `block_seq`。但 mineru 的 layout.json 里 `block_id` 是 per-page 索引，所以 `para` 在**同页内是连续的**（1, 2, 3, ...）。当前已经存到 `kb_chunks.para`，无需迁移。

⚠️ **验证一遍**：跑 `SELECT para, count(*) FROM kb_chunks WHERE kb_doc_id = ? GROUP BY para` 看 `para` 是否从 0/1 连续。  
如果某些文档 `para` 是 MinerU 的 `block_id`（跳过空白 block），那就**天然不连续**——邻接 SQL 仍能工作，只是 `BETWEEN 2 AND 4` 可能跳过 3。这种情况下我们改为 **`BETWEEN hit.para - W AND hit.para + W` 包含自身**（inclusive）——不要求 block 间连续，**有就拼、没有就跳过**。✅ 现有数据不需要 backfill。

### 步骤 1：加 SQL helper 给 `kb_chunks` 拉同页 window

**新建** `backend/app/services/sentence_window.py`：

```python
"""Sentence-Window: pull neighbour chunks around a hit for context.

Why
---
MinerU splits a PDF into paragraph-level blocks. A single chunk often
contains the *answer* but not the *context that makes the answer
safe to repeat*. E.g. "Referral to SPC / Treaty is required" — the
LLM, given only that line, will write a generic "referral is
mandatory" answer; given the surrounding paragraph it knows SPC and
Treaty are *named recipients* and will quote them.

Pattern (sentence-window retrieval): match small, return big.

This module only handles retrieval-side stitching. Index-side is
unchanged — MinerU already gives us per-block chunks with `page` +
`para` (block_id) continuity.
"""
from __future__ import annotations
from typing import Iterable
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_window(
    session: AsyncSession,
    *,
    kb_doc_id: int,
    page: int,
    para: int,
    window: int,
) -> list[dict]:
    """Return all kb_chunks with `para` in [para-window, para+window],
    same kb_doc_id + page.

    Empty list if `window == 0` or page is None. Sparse `para` values
    (MinerU sometimes skips whitespace blocks) are handled gracefully —
    we just take whatever falls in the inclusive range.
    """
    if window <= 0 or page is None or para is None:
        return []
    rows = (
        await session.execute(
            text(
                """
                SELECT id, kb_doc_id, page, para, text, snippet,
                       bbox_json, ragflow_chunk_id, embedding_model
                FROM kb_chunks
                WHERE kb_doc_id = :doc_id
                  AND page = :page
                  AND para BETWEEN :lo AND :hi
                ORDER BY para ASC
                """
            ),
            {"doc_id": kb_doc_id, "page": page, "lo": para - window, "hi": para + window},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def stitch_text(siblings: list[dict]) -> str:
    """Concatenate sibling chunks with `\n\n` boundaries.

    The middle chunk's content is what we originally matched; the
    surrounding siblings add context. Caller is responsible for
    keeping the bbox / citation_key of the *middle* chunk.
    """
    parts = [s["text"].strip() for s in siblings if s.get("text")]
    return "\n\n".join(parts)
```

### 步骤 2：把 window 拼接到 `retrieve()`

**改** `backend/app/services/local_retriever.py`：
- 在 return 前加一个 step 6.5：对每条 hit，调 `fetch_window()`，把 `content` 替换成 stitched text；
- 设置 `match_source` 标记 `+window`（例如 `"bm25+window"`）方便调试——但保持与既有 `"both"` 兼容；
- 设置 `window_size` 字段（拼了几个 sibling）。

具体位置在 line 401 之前：

```python
# 6.5. Sentence-window: stitch neighbouring chunks into the
#      matched chunk's `content`. We don't touch bbox / citation_key
#      / match_source — only the body the LLM sees.
if settings.rag_window_size > 0:
    for hit in hits:
        if not hit.get("kb_doc_id") or not hit.get("page"):
            continue
        siblings = await fetch_window(
            session,
            kb_doc_id=hit["kb_doc_id"],
            page=hit["page"],
            para=hit.get("para"),
            window=settings.rag_window_size,
        )
        if len(siblings) <= 1:
            continue
        hit["content"] = stitch_text(siblings)
        hit["window_size"] = len(siblings)
```

**关键约束**：bbox/citation_key 不变 → PDF 高亮仍精准落在中间 chunk；footer 短链仍只显示真正命中的 chunk。

### 步骤 3：可配置开关

**改** `backend/app/config.py`：

```python
rag_window_size: int = 1
```

注释说明：0 = 关闭（退化到原行为），1 = 前后各 1 个 block，2 = 前后各 2 个，依此类推。

### 步骤 4：测试

**新建** `backend/tests/test_sentence_window.py`：
- 单测 `fetch_window` 在 missing page / sparse para / 边界 window 下行为；
- 单测 `stitch_text` 拼接顺序、空 chunk 跳过、`\n\n` 分隔；
- **关键端到端**：构造 mock hit + mock siblings，验证 hit.content 被替换成 stitched text、bbox/citation_key 不变。

集成测试（用真实数据）：
- 重发"if people work on offshore rigs/platforms, who needs to referral"；
- 期望：bot 回答里**字面**出现 **"Referral to SPC / Treaty"** + **"Referral to SPC is required for any risks that are excluded by"**——这些精确术语现在嵌在拼接的上下文里，LLM 有底气引用。

### 步骤 5：监控 + 调参

每次 `fetch_window` 调用给日志一行 `windowed hit kb_doc_id=X page=Y para=2 → 3 siblings`——方便 ops 看哪些 hit 触发了 window、避免召回上下文压垮 token 预算。

---

## 涉及文件清单

| 操作 | 路径 |
|------|------|
| 新建 | `backend/app/services/sentence_window.py` |
| 改 | `backend/app/services/local_retriever.py`（retrieve 末尾加 step 6.5） |
| 改 | `backend/app/config.py`（`rag_window_size` 默认 1） |
| 新建 | `backend/tests/test_sentence_window.py` |

---

## 假设与决策

- **window_size 默认 1**：保守起步。3 个 block 在 95% 的场景足够 LLM 理解上下文；2 (5 block) 留给 ops 调优。  
- **不动 `kb_chunks` schema**：`para` 字段已经够用，不需要新加 `block_seq` 列。  
- **不重 embed**：sentence-window 只动 `content` 字段，不影响 `embedding` / `tsv`。  
- **bbox 不扩展**：保持原 bbox，PDF 高亮精准在命中 chunk 上；上下文只影响 LLM 看的文字。  
- **不动 prompt**：用户拒绝了 prompt 强制约束的方案；sentence-window 是结构化方案，更稳。  
- **可逆**：`rag_window_size=0` 完全退化到原行为，紧急回滚不影响其他改动。

---

## 验证步骤

1. `cd backend && pytest tests/test_sentence_window.py` → 通过。  
2. 容器重启 + 重发用户问题：bot 回答里**字面**出现 "Referral to SPC / Treaty is required"。  
3. 点击上标：PDF viewer 仍精准高亮**原** chunk（不是 window 拼接出来的整段）。  
4. `EXPLAIN` window 查询：确认 `(kb_doc_id, page, para)` 索引命中。  
5. token 预算：观察 5 个 hit × 3 siblings 平均会让 prompt 长 ~3×——必要时把 `ragflow_top_n_after_rerank` 从 5 降到 4 抵消。

---

## 调研来源

- [LangChain — Parent Document Retriever](https://python.langchain.com/docs/modules/data_connection/retrievers/parent_document_retriever)  
- [ai-tldr.dev — What Is Parent Document Retrieval in RAG?](https://ai-tldr.dev/learn/rag/advanced-rag/parent-document-retrieval/)（sentence-window 同名词条）  
- [AI Wiki — Parent Document Retriever Guide](https://www.artificial-intelligence-wiki.com/ai-development/rag-systems/parent-document-retriever/)  
- [LangChain Reference — ParentDocumentRetriever](https://reference.langchain.com/python/langchain-classic/retrievers/parent_document_retriever/ParentDocumentRetriever)  
- [Ailog — Récupération de Document Parent : Contexte Sans Bruit](https://app.ailog.fr/fr/blog/guides/parent-document-retrieval)（window retrieval 命名）