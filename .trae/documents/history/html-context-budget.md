# HTML 文档渲染 + 跨轮上下文注入 + max_tokens 预算分级

> 实现记录 — commit `6f2c71f` "fix(chat,kb): HTML 文档 iframe 渲染 + 跨轮上下文注入 + max_tokens 预算分级"

## 1. 问题

三个独立但同期浮现的问题：

1. **HTML 文档预览走了 sandbox iframe**，但 markdown 渲染阶段没正确放行，导致内容被 sanitize 掉
2. **同任务多轮对话上下文断裂**：bot 每轮只看当前 message，丢失前几轮的内部状态
3. **大模型输出截断**：固定 max_tokens=2048 对长文档分析不够

## 2. 改动

### 2.1 HTML 文档渲染

`frontend/lib/markdown.ts`：

- `<details>` 折叠 source viewer
- sandbox iframe 隔离 HTML
- markdown-it 自定义 rule：识别 ` ```html ` 代码块转 iframe

### 2.2 跨轮上下文

`backend/app/api/chat.py` 加 `_load_prior_history`：同一 task_id 前 N 轮 bot 发言注入 system prompt。

测试：`backend/tests/test_chat_history.py`（按 task_id 连续 3 轮，最后一轮 system prompt 含前两轮 bot 名）

### 2.3 max_tokens 预算分级

`backend/app/config.py` + `backend/app/orchestrator/msghub.py`：

| 任务类型 | max_tokens |
| --- | --- |
| 普通聊天 | 2048 |
| 文档分析 / 长输出 | 4096 |
| 总结（summary） | 1024 |

测试：`backend/tests/test_max_tokens_budget.py`

## 3. 验证

- HTML 文档能正常预览且 source 可查
- 跨 3 轮对话的 bot 能引用前轮内容
- 大文档分析不再截断（手动跑 docx）