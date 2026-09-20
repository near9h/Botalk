# frontend/lib

> 客户端工具（api / 类型）。

## 文件

| 文件 | 作用 |
| --- | --- |
| `api.ts` | `api` 对象：所有后端端点的 fetch 包装 + 类型导出 |
| `markdown.ts` | markdown-it 包装 + sanitize |
| `pdf.ts` | PDF.js helper |
| … | 其他工具 |

## `api.ts` 结构

```ts
export const api = {
  // Auth
  login, logout, me,
  // Bots
  listBots, createBot, updateBot, deleteBot,
  // KB
  listKbs, createKb, updateKb, deleteKb,   // ← updateKb 新增（ae0bae1）
  listKbDocuments, getKbDocument, deleteKbDocument, uploadKbDocument,
  getKbChunk, listKbDocumentChunks,
  // Chat
  streamChat, ...
}
```

## 约定

- 所有 fetch 走 `request<T>()` 包装（统一错误 + 凭证）
- 类型显式导出，路由文件 `import { KnowledgeBase } from "@/lib/api"`
- SSE 用 `fetch` + `ReadableStream` 或浏览器 `EventSource`