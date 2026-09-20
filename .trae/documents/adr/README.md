# ADR — 架构决策记录

> Architecture Decision Records。Michael Nygard 模板。
> 每个决策 = 一个 markdown 文件 + 状态 + 日期 + 后果。

| 编号 | 标题 | 状态 |
| --- | --- | --- |
| [0001](0001-three-tier-compose.md) | 单机 Docker Compose 三层部署 | Accepted |
| [0002](0002-orchestrator-choice.md) | 自研编排器 vs AgentScope | Accepted |
| [0003](0003-sse-vs-websocket.md) | 流式用 SSE 而非 WebSocket | Accepted |
| [0004](0004-kb-local-rag.md) | KB 默认本地 BM25+向量 | Accepted |

## 写作模板

```markdown
# ADR-NNNN: 标题

- **状态**：Proposed / Accepted / Deprecated / Superseded by ADR-XXXX
- **日期**：YYYY-MM-DD
- **决策者**：谁拍板

## 背景

问题是什么。

## 选项

每个选项 + 优劣。

## 决策

选了什么 + 为什么。

## 后果

正向 + 风险。

## 相关

链接。
```

## 编号规则

- 顺序编号
- 一旦发版不重用
- 取代旧决策：保留旧 ADR，标 `Superseded by ADR-NNNN`，新增 ADR 写反向引用