# ADR-0001: 单机 Docker Compose 三层部署

- **状态**：Accepted
- **日期**：2026-09-16
- **决策者**：架构组

## 背景

项目早期需要快速交付。需要决定：单机自托管 vs k8s vs Serverless。

## 选项

| 选项 | 优劣 |
| --- | --- |
| 单机 Docker Compose | ✅ 5 分钟起；❌ 单点 |
| k8s | ❌ 团队无 k8s 经验；运维成本高 |
| Serverless（Cloud Run） | ❌ NewAPI 在内网，无法走云函数 |

## 决策

**单机 Docker Compose**，原因：当前用户规模 < 100，单机足够；运维门槛最低。

## 后果

- ✅ 5 分钟交付
- ✅ 升级 / 回滚简单
- ⚠️ 单点故障：Postgres 挂了 = 全挂；靠 [09-operations/backup-restore.md](../09-operations/backup-restore.md) 兜底
- ⚠️ 用户量 > 1000 时需重评估 k8s

## 相关

- [04-architecture/README.md § 4](../04-architecture/README.md)
- [08-deployment/README.md](../08-deployment/README.md)