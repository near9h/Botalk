# ADR-0003: 流式用 SSE 而非 WebSocket

- **状态**：Accepted
- **日期**：2026-09-18
- **决策者**：架构组

## 背景

流式 chat 输出要选传输协议。

## 选项

| 选项 | 优劣 |
| --- | --- |
| SSE（Server-Sent Events） | ✅ 单向（够用）；✅ 简单；✅ 浏览器原生 EventSource；❌ 不支持双向 |
| WebSocket | ✅ 双向；❌ 复杂度高；❌ nginx / 防火墙配置难 |
| 长轮询 | ❌ 延迟高；❌ 服务端开销大 |

## 决策

**SSE** + 浏览器 `EventSource` API。

理由：

1. bot 流式输出天然单向（服务端 → 浏览器）
2. Nginx 直接支持（关闭 `proxy_buffering` 即可，已在 nginx.conf）
3. HTTP/2 多路复用足够；不需要 WebSocket 的全双工
4. 调试简单：`curl -N` 就能看

## 后果

- ✅ 实现简单（`backend/app/api/chat.py`）
- ✅ 调试工具成熟
- ✅ 防火墙友好
- ⚠️ 若后续要做"客户端中途取消生成"，仍可走 SSE + AbortController（已实现）

## 相关

- `backend/app/api/chat.py` — 端点 `/api/chat/stream`
- `frontend/lib/api.ts` — `EventSource` 封装