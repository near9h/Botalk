# 方案：AI 回答引用的稳定化（脱离 prompt 控制）

## 摘要

BotGroup 当前在 AI 回答里插入 KB 引用靠的是 LLM 主动在文本里写 `[doc: filename p.X ¶Y]` 标记。这种"prompt 约束"在用户实测里**不稳定**——LLM 会忘、改格式、跳过引用甚至把整段输出截掉。本方案**完全去掉对 prompt 的依赖**，改为**后处理式 posthoc span alignment**（业内最强方案）。

实施要点：

1. 后端在 `_generate_agent` 拿到 LLM 纯文本后，**按句号/问号切分**为原子句；
2. 对每个原子句用 embedding 算与召回 chunks 的余弦相似度，**句子级归因**；
4. 按出现顺序给句子末尾追加 `[N]` 上标，**注入到原文**；
5. 同时把现在的"prompt 强约束"全部回滚——让 LLM 只管写好内容，引用交给后处理；
6. 顺手修上一轮截图里的"气泡空白"问题——定位+修复。

---

## 调研结论：业内方案对比

参考 5 篇 2026 年权威资料（清华 CEG 论文、FullCite 论文、ai-tldr.dev、agentbus、SitePoint 字节级 grounding 验证），业内有四类方案：

| 方案 | 代表产品 | snippet-F1 | 实现复杂度 | 适用场景 |
|------|---------|-----------|-----------|---------|
| **A. Prompt-based（让 LLM 自己写标记）** | NotebookLM、Perplexity 初版 | **12.80**（ASQA，FullCite 数据） | ⭐ | 强 LLM + 简洁 context |
| **B. Posthoc span alignment（句子↔chunk embedding 对齐）** | 清华 CEG、FullCite、agentbus 推荐 | **61.87**（同 benchmark） | ⭐⭐⭐ | 通用，最强兜底 |
| **C. Constrained decoding over citation grammar** | 研究阶段（FSA 强制 citation token） | 论文级数据 | ⭐⭐⭐⭐⭐ | 极严苛事实要求 |
| **D. Tool-call / Function-call cite_chunks** | OpenAI/Qwen function-calling | ~100% 调用率 | ⭐⭐⭐⭐ | 需 schema 解析 |

**关键数据**：FullCite 论文明确证明 **posthoc（B）比 prompt（A）强 5 倍**。清华 CEG 用 B 思路 + NLI 校验，做到事实召回率超过 SOTA。

**业内共识**：

> "Post-hoc attribution splits the answer into sentences, embeds each sentence, and retrieves the best-matching chunk from the vector store for that sentence. The sentence-to-chunk similarity score becomes the citation confidence. This works reasonably well."
> — [ai-tldr.dev](https://ai-tldr.dev/learn/rag/advanced-rag/add-citations-to-rag/)

**产品视角**：

> "NotebookLM citations are near-perfect within their scope. Every claim in a response includes a footnote linking to the exact passage in your source document. You can click the citation and see the highlighted sentence it came from."
> — [thebestaitools.co](https://thebestaitools.co/comparisons/notebooklm-vs-perplexity-vs-chatgpt-for-document-research/)

NotebookLM 之所以事实召回率高，不是因为 prompt 强——是因为它强制 source-grounded（拒绝回答 source 外的所有内容）。**我们做不到这种激进约束**（我们的 bot 是开放领域聊天 + KB 增强），所以 posthoc 是正解。

**结论**：选 **方案 B（posthoc span alignment）**，加 **NLI 二次校验**（用 sentence↔chunk embedding 阈值过滤弱对齐）。

---

## 现状分析

### 当前链路（基于 Phase 1 探索结果）

| 步骤 | 文件:行 | 做了什么 | 痛点 |
|------|--------|---------|------|
| RAG 召回 | `backend/app/services/local_retriever.py:187-302` | pgvector ANN 检索 → top_n chunks | 没问题 |
| Prompt 注入 | `backend/app/services/rag_retriever.py:156-191` | 在 system prompt 末尾追加 `【知识库参考】[doc: …]` 块 | LLM 不会逐句引用 |
| LLM 生成 | `backend/app/orchestrator/msghub.py:280-618` `_generate_agent` | 同步 chat completion, `max_tokens=512`（无 doc skill 时） | 输出预算紧；LLM 改格式 / 跳过 |
| SSE 推送 | `backend/app/api/chat.py:192-231` | 把 `full` + `cited_refs` 推到前端 | OK |
| 前端渲染 | `frontend/lib/markdown.ts:280-302` | 正则匹配 `[doc: …]` → 上标 `[1][2]` | 必须 LLM 写标记 |
| Footer 短链 | `frontend/components/CitedRefsFooter.tsx` | 永远显示所有 chunks | 没问题 |

### 关键问题

1. **prompt 约束不稳定**：用户实测截图（`run_id = 1885`，msg 983/984/985/986）只有 msg 985 真正带 `[doc: …]` 标记，其他三条 LLM 都没按 prompt 办事；`cited_refs` 后端都有传。
2. **气泡内容空白**：用户上一轮截图显示 bot 气泡（人事负责人、合规负责人、总结）的正文是空白，只有 footer 短链显示。**根因待本 plan 第一步确认**——三种可能：
   - **(A) `max_tokens=512` 让 LLM 输出被截断**——加强引用 prompt 后，prompt 变长，留给输出的 token 更少；最像；
   - **(B) 前端 SSE 解析 bug**——但 DB 里 content 都有，可能性低；
   - **(C) markdown 渲染 bug**——截图显示矩形框 + 内边距都正常，post-fix；
   - 倾向 (A)，会在排查阶段验证。

### 现有可复用基础设施

- `RetrievedChunk`（`rag_retriever.py:46-71`）——已经有 `chunk_id / snippet / content / citation_key / score`，复用即可。
- `OrchestratorEvent.cited_refs`（`msghub.py:110-116`）——后端→前端的通道已就绪。
- 前端 `<sup class="citation" data-citation-chunk-id="…">` 渲染（`markdown.ts:294`）——由 `[doc: …]` 触发的同一套，已知可用。
- 句子切分 + 文本相似度工具：项目里没有，需新写或引外部库。

---

## 方案设计

### 选 B：posthoc span alignment + embedding 二次校验

**为什么不是 A（继续改 prompt）**：
- 实测已经失败多次（用户截图验证）；
- 论文数据证明 prompt-only snippet-F1 仅 12.80；
- 改 prompt 是"治不到根上"。

**为什么不是 C（constrained decoding）**：
- 实现复杂：需改 OpenAI client 的解码路径，对接各家 SDK 都要 hack；
- 用户接受度低：每句话都必须有 citation token，会污染 LLM 表达的流畅性。

**为什么不是 D（tool-call）**：
- 100% 调用率诱人，但需要 schema 解析；当前已经走过 structured_doc_skill 的复杂 retry 路径，再加一层工具调用会显著增加延迟；
- 对小模型（DeepSeek-V3 / GLM-4）兼容性未必一致。

**选 B 的核心理由**：

1. 论文证明最强（snippet-F1 = 61.87）；
2. 实现集中在 `msghub.py` 后处理钩子，约 100-150 行；
4. 不需要改 OpenAI client，新 API（智谱/DeepSeek/Anthropic）原生支持；
5. 兼容 LLM 自己偶尔写对的 `[doc: …]` 标记（前端 markdown 正则还会命中）。

### 算法步骤

```
输入：
  - answer_text: str   (LLM 完整输出)
  - chunks: list[RetrievedChunk]   (top_n 召回)

步骤 1：句子切分
  SENT_END = /(?<=[。！？!?\n])|(?<=\*\*\s)/  
  sentences = [s.strip() for s in SENT_END.split(answer_text) if s.strip()]

步骤 2：chunk 文本准备
  对每个 chunk 取 target = chunk.content or chunk.snippet

步骤 3：embedding 计算（批量）
  sentence_vecs = embed(sentences)
  chunk_vecs = embed([chunk.content for chunk in chunks])

步骤 4：相似度矩阵
  sim_matrix[i][j] = cosine_sim(sentence_vecs[i], chunk_vecs[j])

步骤 5：归因决策
  for each sentence i:
    best_j = argmax(sim_matrix[i])
    best_score = sim_matrix[i][best_j]
    if best_score >= THRESHOLD (0.55)：  
      aligned.append((i, best_j, best_score))
    else:
      aligned.append((i, None, best_score))  # 不引用

步骤 6：注入上标
  对每个 aligned[i] = (sent_idx, chunk_idx_or_None, score):
    if chunk_idx_or_None is not None:
      在 sentences[sent_idx] 末尾追加 ` [doc: {chunks[chunk_idx].citation_key}]`
  
  full = " ".join(sentences)
  return full, chunks  # chunks 仍传给前端 footer

阈值参数：
  - SIM_THRESHOLD = 0.55（基于用户实际 corpus 调，unit test 里验证）
  - MIN_SENT_LEN = 6 字（短句"好的"、"@xxx" 跳过，避免误对齐）
```

### 阈值与拒判

- 阈值 0.55 来源：ai-tldr 提到的常见阈值区间 0.45-0.6；我们 corpus 是劳动合同法 PDF，文本相对长且结构化，可以略高一点。
- **拒判**（句子与所有 chunk 都不相似）→ 这句子**不注入上标**，但 footer 仍展示 chunks，避免"看起来无引用"的错觉。
- 用户后续可在调参面板调整（暂不做 UI，constant 即可）。

### Embedding 来源

- 项目已用智谱 GLM embedding-3（`backend/app/services/zhipuai_embed.py`）—— 复用它，避免新依赖。
- 单次 LLM turn 的句子数通常 < 20、chunk 数 < 5——一次 batch embedding 调用，**增加延迟 < 200ms**。

---

## 实施步骤

### 步骤 0：先修复"气泡空白"问题（独立子任务）

**目的**：把方案实施前后的"气泡空"基线问题先清掉，避免新方案上线时被同一个 bug 干扰。

1. **定位根因**：用上一轮的 `run_id = 1885` SQL：

   ```sql
   SELECT id, role, length(content), substring(content, 1, 300)
   FROM messages WHERE run_id = 1885 ORDER BY id;
   ```

   确认每个 bot 行的 `content` 实际长度。

2. **判定**：
   - 如果 `length(content) > 0`：是前端 SSE / markdown 渲染 bug，往前端查。
   - 如果 `length(content) = 0`：是后端 LLM 输出被截（`max_tokens=512` 撞顶）或 LLM 直接返空。

3. **修复**：
   - 如果是 (A) `max_tokens`：把 KB bot 的 `max_tokens` 提到 **1024**，并加"截断检测 + 自动续写一次"逻辑（用 LLM 输出的 `finish_reason == "length"` 触发）。
   - 如果是 (B) SSE：补前端 SSE 解析日志（`streamChat` 加 `console.log('[sse]', ev, data)`），让用户复现一次拿到现场。
   - 如果是 (C) markdown：检查 `dangerouslySetInnerHTML` + `renderMessageWithMentions` 对空字符串的输出。

### 步骤 1：新建 `app/services/citation_aligner.py`

**职责**：posthoc span alignment 算法本体。

```python
"""Posthoc citation alignment — sentence↔chunk embedding similarity."""
from dataclasses import dataclass
from difflib import SequenceMatcher
from app.services import zhipuai_embed

@dataclass
class Alignment:
    sentence_idx: int
    chunk_idx: int | None  # None 表示拒判（句子不属于任何 chunk）
    score: float

SIM_THRESHOLD = 0.55
MIN_SENT_LEN = 6

SENT_END = re.compile(r'(?<=[。！？!?\n])|(?=\*\*\s)')
SKIP_PREFIX = re.compile(r'^[\s*\-#>`]+')

def split_sentences(text: str) -> list[str]:
    parts = SENT_END.split(text)
    return [SKIP_PREFIX.sub('', p).strip() for p in parts if p.strip()]

async def align(answer: str, chunks: list) -> list[Alignment]:
    if not chunks or not answer.strip():
        return []
    sents = split_sentences(answer)
    if not sents:
        return []
    # Embed sentences + chunks in one batch
    targets = [c.text or c.snippet for c in chunks]
    vecs = await zhipuai_embed.embed_texts(sents + targets)
    s_vecs = vecs[:len(sents)]
    c_vecs = vecs[len(sents):]
    # Cosine similarity (already normalized by GLM API)
    sim = [[float(np.dot(s, c)) for c in c_vecs] for s in s_vecs]
    aligned = []
    for i, row in enumerate(sim):
        if len(sents[i]) < MIN_SENT_LEN:
            aligned.append(Alignment(i, None, 0.0)); continue
        best_j = max(range(len(row)), key=lambda j: row[j])
        score = row[best_j]
        if score >= SIM_THRESHOLD:
            aligned.append(Alignment(i, best_j, score))
        else:
            aligned.append(Alignment(i, None, score))
    return aligned

def inject_markers(answer: str, chunks: list, aligned: list[Alignment]) -> str:
    sents = split_sentences(answer)
    if not sents:
        return answer
    for a in aligned:
        if a.chunk_idx is not None:
            sents[a.sentence_idx] = sents[a.sentence_idx].rstrip() + \
                f' [doc: {chunks[a.chunk_idx].citation_key}]'
    return " ".join(sents)
```

**注意点**：
- GLM embedding 已归一化，cosine = 点积；不开方。
- 不引入新依赖（用 stdlib + 已有的 zhipuai_embed）。
- 短句（< 6 字）直接跳过，避免对齐到废话。
- 保留 LLM 自己写的 `[doc: …]` 标记——对齐只追加不冲突（同一句子出现两次 `[doc: …]` 不影响前端解析）。

### 步骤 2：把 aligner 接到 `_generate_agent`

**改 `backend/app/orchestrator/msghub.py`**：

1. **新增 import**：
   ```python
   from app.services.citation_aligner import align, inject_markers
   ```

2. **修改 `_generate_agent` return 路径**：
   ```python
   text = _message_text(msg)
   cited_refs = cited_refs  # already built earlier

   if cited_refs and text:
       aligned = await align(text, cited_refs)
       text = inject_markers(text, cited_refs, aligned)
   return text, cited_refs
   ```

3. **`max_tokens` 兜底**：把 KB bot 的 `max_tokens` 提到 **1024**（现状 512）。
   加"截断检测 + 自动续写一次"：

   ```python
   finish = resp.choices[0].finish_reason
   if finish == "length" and not structured_doc_skill:
       # Truncated. Ask model to continue with markers intact.
       messages.append({"role": "assistant", "content": text})
       messages.append({"role": "user", "content": "继续，把引用 [doc: ...] 标记补全。"})
       params["messages"] = messages
       resp = await client.chat.completions.create(**params)
       text += _message_text(resp.choices[0].message)
   ```

### 步骤 3：回滚过激的 prompt 约束

**改 `backend/app/services/rag_retriever.py`**：

把 `_format_context_block` 的强约束 prompt **改回**简洁版：

```python
def _format_context_block(chunks):
    if not chunks:
        return ""
    lines = [
        "【知识库参考】以下是相关资料，可在引用时附上 [doc: filename p.X ¶Y] 标记。"
        "若与问题无关，回答「暂未找到相关资料」。",
    ]
    for c in chunks:
        snippet = c.snippet.replace("\n", " ").strip()
        lines.append(f"[doc: {c.citation_key}] {snippet}")
    return "\n".join(lines)
```

—— 即用方案 A（"改进 prompt"）的最低限度版本，作为 aligner 的兜底（LLM 偶尔写出标记仍能被前端 markdown 正则命中）。**不**继续堆强约束。

### 步骤 4：保持数据流兼容

不需要改 `cited_refs` 在 DB 的存储格式（`Message.cited_refs: JSON`）。

前端 `markdown.ts:280-302` 的正则 `[doc: …]` 依然有效——aligner 注入的标记会被同一 regex 命中、解析成上标。**前端 0 改动**。

### 步骤 5：测试

**单元测试** `backend/tests/test_citation_aligner.py`：
- 5 种典型回答（"结论"型、"列表"型、"含代码块"型、"短答"型、"无关答"型）；
- 用真实 KB chunk（从 pgvector 现成数据取）；
- 验证：
  - 每个有引用价值的句子末尾都有 `[doc: …]`；
  - 阈值过滤生效（无关句子不挂引用）；
  - LLM 已写的 `[doc: …]` 不被破坏（双写也不冲突）。

**集成测试**：
1. `docker compose build backend` + `docker compose up -d --force-recreate backend`。
2. 重发"我要裁员"问题，肉眼检查：
   - 每条事实句末尾是否都跟上 `[1][2]…`；
   - footer 短链 `[1] 中华人民共和国劳动合同法.pdf p.11 ¶8` 仍正常；
   - 点击 `[1]` 打开 PDF viewer 跳转到 p.11。
3. 历史消息刷新后还能渲染——同理（数据已在 DB）。

### 步骤 6：清理调试日志

实施期间为了诊断空气泡问题加的：
- `frontend/lib/markdown.ts:240` 的 `console.log("[md cite] ...")`；
- `frontend/app/group/[id]/page.tsx:80-90` 的 `[citation click]` 调试日志；

—— 在确认根因后**删除**，避免 console 噪音。

---

## 涉及文件清单

| 操作 | 路径 |
|------|------|
| 新建 | `backend/app/services/citation_aligner.py` |
| 新建 | `backend/tests/test_citation_aligner.py` |
| 改 | `backend/app/orchestrator/msghub.py`（import + return 路径 + max_tokens + 截断续写） |
| 改 | `backend/app/services/rag_retriever.py`（`_format_context_block` 回滚） |
| 改 | `frontend/lib/markdown.ts`（删 debug log） |
| 改 | `frontend/app/group/[id]/page.tsx`（删 debug log） |

---

## 假设与决策

- **Embedding 来源**：复用项目已有的 `zhipuai_embed.embed_texts`，避免引入 `numpy` / `torch` 等大依赖。
- **句切分用 stdlib + 正则**：避免引入 `jieba` / `spacy` 增加镜像体积。
- **保留 LLM 主动写的 `[doc: …]`**：aligner 只追加不破坏，作为兜底。
- **阈值 0.55 作为初始值**：unit test 调优；后续可读 settings 暴露给管理员。
- **不动前端 markdown.ts 的渲染逻辑**：已经能正确处理 LLM 自己写标记的路径，aligner 注入的标记走同一条路径。
- **不动 max_tokens 之外的全量外参**：保持单改动原则，避免引入更多变量。

---

## 验证步骤

1. `pytest backend/tests/test_citation_aligner.py` —— 全部通过。
2. `docker compose build backend` + `docker compose up -d --force-recreate backend`。
3. 在 chat 页面发"我要裁员"，肉眼检查每条 fact 后面跟上 `[1][2]…`。
4. 点击 `[1]` → 抽屉打开 PDF p.11，bbox 定位正确。
5. 历史消息刷新后还能渲染（数组在 DB，已被持久化）。
6. 截图反馈给用户确认。

---

## 调研来源

- [ai-tldr.dev — How to Add Citations to RAG Answers](https://ai-tldr.dev/learn/rag/advanced-rag/add-citations-to-rag/)
- [FullCite — Explicit Evidence Grounding via Structured Inline Citation Generation (arXiv 2606.07130)](https://arxiv.org/html/2606.07130v1)
- [CEG — Citation-Enhanced Generation for LLM-based Chatbots (arXiv 2402.16063, 清华)](https://arxiv.org/html/2402.16063v4/)
- [agentbus — How to Implement AI Output Citations and Source Attribution](https://agentbus.sh/posts/how-to-implement-ai-output-citations-and-source-attribution/)
- [Edtek — Hallucination-Proof RAG Architecture (2026 Guide)](https://edtek.ai/kb/hallucination-proof-rag-architecture/)
- [SitePoint — RAG Citation Verification by Deterministic Byte-Span Validators](https://www.sitepoint.com/rag-citation-verification-byte-span-validators-typescript/)
- [thebestaitools — NotebookLM vs Perplexity vs ChatGPT for Document Research](https://thebestaitools.co/comparisons/notebooklm-vs-perplexity-vs-chatgpt-for-document-research/)
- [amicited — The Anatomy of an AI-Generated Answer: Where Citations Happen](https://www.amicited.com/blog/ai-answer-anatomy-citations/)