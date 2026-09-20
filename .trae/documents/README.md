# .trae/documents — 项目文档总入口

> botgroup 的全部项目级文档。按 PMP / PMBOK 10 大知识领域组织，
> 同时满足**项目审计**和**PMP 追踪**需求，运维团队也能按 Runbook 接管。

---

## 📖 总目录

### 章节（按 PMP 顺序）

| # | 章节 | 目录 | 用途 |
| --- | --- | --- | --- |
| 01 | 立项管理 | [01-initiation/](01-initiation/) | charter / 干系人 / 里程碑 |
| 02 | 规划 | [02-planning/](02-planning/) | PM plan / 选型 / 风险 |
| 03 | 需求 | [03-requirements/](03-requirements/) | 业务/干系人/方案需求 + RTM |
| 04 | 架构 | [04-architecture/](04-architecture/) | 系统总览 + 子系统设计 |
| 05 | 详细设计 | [05-design/](05-design/) | 模块清单 + 接口 + UI |
| 06 | 实现记录 | [06-implementation/](06-implementation/) | 每个 feature 怎么落地的 |
| 07 | 测试 | [07-testing/](07-testing/) | 单元/集成/UAT + 安全审计 |
| 08 | 部署 | [08-deployment/](08-deployment/) | 镜像 / 端口 / env |
| 09 | 运维 | [09-operations/](09-operations/) | Runbook / On-call / 备份 / 应急 |
| 10 | 收尾 | [10-closure/](10-closure/) | 收尾清单 + 经验教训 |

### 辅助

| 目录 | 作用 |
| --- | --- |
| [adr/](adr/) | 架构决策记录（4 份） |
| [appendix/](appendix/) | 进度追踪表 / 联系人 / 工具链 |
| [history/](history/) | 历史方案归档（开发期沉淀的 *plan.md / *report.md） |

---

## 🎯 角色 → 入口

| 角色 | 看哪里 |
| --- | --- |
| 项目经理（PMP） | 01 charter → 02 PM plan → 10 closure |
| 架构师 | 04 架构（[system-architecture.md](04-architecture/system-architecture.md) / [middleware-inventory.md](04-architecture/middleware-inventory.md) / [data-flow.md](04-architecture/data-flow.md)）→ adr/ |
| 开发 | 05 详细设计 → 06 实现记录 → 各自模块 README |
| 测试 | 07 testing → 09 smoke-test |
| 运维（接手） | 09 operations（5 份手册） → 08 deployment → 04 [middleware-inventory.md](04-architecture/middleware-inventory.md) |
| 安全审计 | 07 testing / security-audit-report.md → 09 user-mgmt-audit-log.md |
| 业务方 | 03 需求 → 10 closure |

---

## 📋 模块 README（代码内）

后端：[backend/app/README.md](../../backend/app/README.md)
前端：[frontend/README.md](../../frontend/README.md)

---

## 🔗 相关

- 仓库根 [README.md](../../README.md)（用户向）
- CI：[.github/workflows/ci.yml](../../.github/workflows/ci.yml)
- 最近 commits：`git log --oneline -10`

---

## 📜 版本

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| 1.0 | 2026-09-20 | 首版（按 PMP 10 章 + ADR + 模块 README 体系整理） |