# backend/app/services

> 跨模块业务服务层。无 HTTP 状态，可被任意路由 / worker 调用。

## 文件

| 文件 | 作用 | 调用方 |
| --- | --- | --- |
| `audit.py` | 审计中间件 + 表操作 | 所有路由 |
| `rag_retriever.py` | 主 RAG 检索（融合） | orchestrator |
| `local_retriever.py` | 本地 BM25 + 向量 | rag_retriever |
| `ragflow_client.py` | RAGFlow HTTP 客户端 | rag_retriever |
| `citation_aligner.py` | snippet ↔ 原文 对齐 | chat 引用 |
| `sentence_window.py` | 上下文窗口扩展 | RAG |
| `policy.py` | 群组策略（防火墙） | orchestrator |
| `community.py` | 群组动态聚类（探索） | 未来 |
| `language_detect.py` | 中英文启发式检测 | orchestrator |
| `mineru.py` | PDF 解析包装 | workers |
| `office_pdf.py` | Office→PDF（LibreOffice） | workers |
| `zhipuai_embed.py` | Embedding（zhipuai） | local_retriever |
| `mcp.py` | MCP 协议适配 | 未来 |

## 通用约定

- **无状态**：除 `audit` 外都不持有数据库连接；调用方传 session
- **纯函数优先**：能写纯函数就纯函数，方便单测
- **错误**：自定义异常，路由层翻译成 HTTP

## 测试

每个 service 在 `backend/tests/` 至少 1 份单测。