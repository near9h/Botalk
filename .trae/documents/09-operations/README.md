# 09 运维（Operations & Maintenance）

> PMBOK 第 12 章：项目采购 / 资源 / 干系人；本目录装运维可执行的全部手册。

---

## 1. 部署后运维资产清单

| 资产 | 位置 | 备注 |
| --- | --- | --- |
| 公网入口 | `https://36.151.149.30:3500` | Nginx stream-routing (HTTP+HTTPS 同端口) |
| Docker Compose | [`docker-compose.yml`](../../../docker-compose.yml) | 单机一键 |
| 容器清单 | `backend / frontend / nginx / postgres / new-api` | |
| 数据库 | `botgroup-postgres` (pgvector/pg16) | |
| 配置 | `.env`（已 gitignore）+ `.env.example`（仓库/git-safe） | |
| 备份策略 | [backup-restore.md](backup-restore.md) | |
| 应急手册 | [incident-response.md](incident-response.md) | |
| On-call | [on-call.md](on-call.md) | |
| 烟囱测试 | [smoke-test.md](smoke-test.md) | |
| 升级 | [upgrade.md](upgrade.md) | |

---

## 2. 日常巡检 SOP

每天 / 每周各做一次：

### 2.1 每日（5 分钟）

```bash
# 容器健康
docker ps --format '{{.Names}}\t{{.Status}}'

# 后端日志（错误 / 异常）
docker compose logs --tail=200 backend | grep -iE 'error|exception|traceback'

# 数据库连接数
docker exec botgroup-postgres psql -U botgroup -d botgroup -tAc \
  "SELECT count(*) FROM pg_stat_activity WHERE datname='botgroup';"

# 磁盘
df -h /var/lib/docker
```

### 2.2 每周（15 分钟）

```bash
# 备份数据库（见 backup-restore.md）
./scripts/backup.sh

# 审计日志异常（高频失败登录）
docker exec botgroup-postgres psql -U botgroup -d botgroup -tAc \
  "SELECT action, count(*) FROM audit_log \
   WHERE created_at > now() - interval '7 days' \
   GROUP BY action ORDER BY 2 DESC LIMIT 20;"

# 数据库表大小
docker exec botgroup-postgres psql -U botgroup -d botgroup -tAc \
  "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) \
   FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;"
```

---

## 3. 服务清单与端口

| 服务 | 端口（内 / 外） | 健康检查 |
| --- | --- | --- |
| frontend | 3000 / — | `curl http://frontend:3000` |
| backend | 8000 / — | `curl http://backend:8000/health` |
| nginx | — / 3500 | `curl -k https://<host>:3500/` |
| postgres | 5432 / — | `pg_isready -U botgroup` |
| new-api | 5000 / — | `curl http://new-api:5000/v1/models` |

---

## 4. 监控指标（手工 + 简易）

| 指标 | 取值 | 阈值 |
| --- | --- | --- |
| 后端 5xx 比例 | `docker logs backend | grep -c ' 5[0-9][0-9] '` | < 0.5% |
| audit_log 单日增长 | `SELECT count(*) FROM audit_log WHERE created_at > now() - interval '1 day'` | 业务基线 × 2 |
| 数据库表 `messages` 行数 | 单表 > 1M 时考虑归档 | 软阈值 1M |
| 容器 OOM | `docker stats` | 重启次数 > 5/小时 |

> 暂未接入 Prometheus / Grafana；上线量级未到。先用上述 shell 一分钟搞定。

---

## 5. 升级 / 回滚

[upgrade.md](upgrade.md)。

---

## 6. 应急响应

[incident-response.md](incident-response.md)。

---

## 7. 用户与审计

[user-mgmt-audit-log.md](user-mgmt-audit-log.md)（沉淀历史方案）。

---

## 8. 相关链接

- [08 部署](../08-deployment/)
- [10 收尾](../10-closure/)