# 07 测试（Testing）

> PMBOK 第 8 章：项目质量管理 之 测试过程。

---

## 1. 测试策略

| 层级 | 范围 | 工具 |
| --- | --- | --- |
| 单元 | services + 工具函数 | pytest + pytest-asyncio |
| 集成 | API 路由 + DB | pytest + httpx ASGI client |
| 端到端 | curl + UI 走查 | 见 [09-operations/smoke-test.md](../09-operations/smoke-test.md) |
| 安全 | 审计 / 权限 / 输入验证 | 见下方安全审计 |
| 性能 | 单次 SSE 流 P95 < 30s | 暂未自动化（NewAPI 侧耗时主导） |

---

## 2. 当前测试目录

`backend/tests/`：

| 文件 | 覆盖点 |
| --- | --- |
| `test_language_detect.py` | 中英文启发式 |
| `test_msghub_lang_directive.py` | bot + summary 语言跟随 |
| `test_citation_aligner.py` | snippet ↔ 原文对齐 |
| `test_audit.py` | 审计中间件 |
| `test_max_tokens_budget.py` | `run_group_discussion` max_tokens 分级 |
| `test_local_retriever.py` | BM25 + 向量 |
| …（其余随需补） |

运行：`cd backend && pytest -q`

---

## 3. 安全审计（独立小节）

详见 [security-audit-plan.md](security-audit-plan.md) + [security-audit-report.md](security-audit-report.md) + [audit-fixes-high-critical.md](audit-fixes-high-critical.md)。

**当前评级**：高危 0 / 中危 1 / 低危 3（详见报告）

**已修复项**：参见 [audit-fixes-high-critical.md](audit-fixes-high-critical.md)

---

## 4. 验收测试（UAT）

每次大改后跑 [09-operations/smoke-test.md](../09-operations/smoke-test.md)，覆盖：

- 登录 / 退出
- 建 bot / 群组
- 流式对话 + 引用
- 上传文档 → KB 检索 → 引用
- 重命名 / 删除 KB

---

## 5. 回归基线

| 项 | 基线 |
| --- | --- |
| pytest 通过率 | 100% |
| tsc 错误数 | 0（业务代码） |
| 安全审计 | 高危 = 0 |

任何 PR 不允许降低基线。

---

## 6. 相关链接

- [06 实现记录](../06-implementation/)
- [09 运维 / smoke-test](../09-operations/smoke-test.md)
- [history/](../history/)（老测试方案）