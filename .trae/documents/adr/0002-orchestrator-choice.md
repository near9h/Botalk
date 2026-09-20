# ADR-0002: 自研编排器 vs AgentScope

- **状态**：Accepted
- **日期**：2026-09-17
- **决策者**：架构组

## 背景

多 bot 群聊的核心是"调度"——谁来发言、何时停。框架上有自研和引入 AgentScope 两种思路。

## 选项

| 选项 | 优劣 |
| --- | --- |
| 自研（基于 Python async） | ✅ 完全可控；✅ 可深度审计；❌ 开发工作量大 |
| AgentScope MsgHub | ✅ 现成多 Agent；❌ 框架侵入重；❌ 自定义审计流困难 |

## 决策

**自研**，但借鉴 AgentScope 的概念（hub / single round / multi round）。`backend/app/orchestrator/msghub.py` 是产物。

理由：

1. 审计要求每一步进 `audit_log`，框架拦截太深；自研可以在 `_generate_agent` 入口 / 出口直接打点
2. 模型调用走 NewAPI（OpenAI 兼容），无需 AgentScope 的多厂商适配
3. 调度策略只 3 种（auto/round_robin/manual），自研 200 行就够

## 后果

- ✅ 全代码可控；审计好做
- ✅ 加新策略成本低
- ⚠️ 需要维护自研编排器（人离开风险）
- ⚠️ 后续若引入 tool-use / multi-agent 协作评估重写

## 相关

- [04-architecture/rag-design.md § 编排](../04-architecture/rag-design.md)
- [../06-implementation/i18n-completion.md](../06-implementation/i18n-completion.md)（最近改动）