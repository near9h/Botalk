# 02 规划（Planning）

> PMBOK 第 6 章：项目规划过程组。本目录沉淀"计划怎么做"的全部产出。

---

## 1. 项目管理计划（Project Management Plan）

### 1.1 范围管理

- **WBS**：按 `bot / group / message / kb / audit / rag / 编排` 7 个特性域拆分；每个域一份 feature plan。
- **范围基准**：本期含 14 个 API 模块 + 20 个前端组件 + 10 个 services 子模块（详见 [04 架构](../04-architecture/)）。
- **范围变更控制**：所有改动走 PR + commit message 关键字（`feat / fix / refactor / docs`），破坏性改动在 PR 描述里标 BREAKING。

### 1.2 进度管理

- **方法**：滚动冲刺（Sprint），每个功能点 = 一个冲刺项。
- **跟踪**：commit history + GitHub Actions CI 状态 + 本目录 commit log。
- **可视化**：详见 [appendix/进度追踪表.md](../appendix/进度追踪表.md)。

### 1.3 成本管理

- **基础设施**：0（自托管）
- **模型调用**：按 NewAPI 用量计（业务侧）
- **人力**：开发自驱；PMP 任命后单点跟踪

### 1.4 质量管理

- **CI**：[.github/workflows/ci.yml](../../../.github/workflows/ci.yml) 跑 backend pytest + frontend tsc noEmit
- **代码审计**：见 [07-testing/security-audit-plan.md](../07-testing/security-audit-plan.md)
- **审计追踪**：详见 [审计列设计](../09-operations/user-mgmt-audit-log.md)

### 1.5 资源管理

| 资源 | 数量 | 用途 |
| --- | --- | --- |
| 后端 Python 工程师 | 1 | FastAPI + 编排 |
| 前端 TS 工程师 | 1 | Next.js + 流式渲染 |
| DBA | 0.2 | PostgreSQL schema / 迁移 |
| 运维 | 0.2 | Docker / Nginx |
| 安全审计 | 0.1 | 见 [security-audit-report](../07-testing/security-audit-report.md) |

### 1.6 沟通管理

| 事件 | 频率 | 产物 |
| --- | --- | --- |
| 日站会 | 每日 | commit log |
| 周会 | 每周 | 本目录更新 |
| 安全审计 | 月度 | security-audit-report 增量 |
| PMP 审查 | 季度 | charter / plan 修订 |

### 1.7 风险管理

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| NewAPI 不可用 | 高 | 调用层超时重试 + 熔断；备用 NewAPI（new-api 容器） |
| 大文档解析超时 | 中 | 后台 worker + 状态轮询；超时 doc 标 failed |
| LLM 输出截断 | 中 | max_tokens 分级 + 续接句式 |
| 单点故障（PostgreSQL） | 中 | 定期备份脚本（见 [09-operations/backup-restore.md](../09-operations/backup-restore.md)） |

### 1.8 采购管理

无外部采购。

### 1.9 干系人管理

见 [01 立项 / 干系人登记](../01-initiation/README.md#4-干系人登记stakeholder-register)。

---

## 2. 选型调研

详见 [market-survey.md](market-survey.md)（开源方案对比）。

**核心结论**：

- AgentScope 的 MsgHub 多 Agent 编排能直接满足"群聊对抗"需求，**自研** 而不引入庞大框架；
- 流式渲染走 SSE + EventSource，**不用 WebSocket**（避免双向通信复杂度）；
- 文档解析走 MinerU + LibreOffice headless，**不依赖 RAGFlow 服务**（解耦部署）。

---

## 3. 相关链接

- [01 立项](../01-initiation/)
- [03 需求](../03-requirements/)
- [04 架构](../04-architecture/)
- [appendix/进度追踪表](../appendix/进度追踪表.md)