# backend/app/orchestrator

> 多 bot 群聊调度核心（自研，参考 AgentScope MsgHub 概念）。

## 文件

| 文件 | 作用 |
| --- | --- |
| `msghub.py` | 单任务多 bot 调度；三种策略（auto/round_robin/manual）+ summary |
| `runner.py` | 单 bot 调用的最小单元：构造 system prompt → 调 NewAPI → 落库 |
| `bots.py` | bot 工具：构造 ReActAgent 等 |

## 关键流程

### msghub._generate_agent

```
对当前轮次的某个 bot：
  1. 拉历史 messages
  2. 加载 prior history（同一任务跨轮）
  3. 注入 persona + [回复语言] 指令
  4. 跑 ragflow / 本地检索（如果挂 KB）
  5. 调 NewAPI（流式）
  6. 写回 message（含 chunk 引用）
  7. audit log
```

### msghub._summarize

```
对任务结束：
  1. 收集所有 bot 发言
  2. 检测用户语种
  3. 注入 [回复语言] system 模板（双语模板）
  4. 调 NewAPI 生成 📋 总结
  5. 落库
```

## 文档

- ADR：[.trae/documents/adr/0002-orchestrator-choice.md](../../../.trae/documents/adr/0002-orchestrator-choice.md)
- 实现记录：[.trae/documents/06-implementation/i18n-completion.md](../../../.trae/documents/06-implementation/i18n-completion.md)

## 测试

- `tests/test_msghub_lang_directive.py` — 语言指令注入
- `tests/test_max_tokens_budget.py` — max_tokens 分级