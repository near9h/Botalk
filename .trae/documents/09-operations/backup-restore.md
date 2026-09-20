# 备份与恢复（Backup & Restore）

> PMBOK § 9.5 / 运维 SOP。

## 1. 备份策略

| 频率 | 保留 | 方法 |
| --- | --- | --- |
| 每日 02:00 | 7 天 | pg_dump 压缩到 `/var/backups/botgroup/daily/` |
| 每周日 03:00 | 4 周 | 同上，路径 `weekly/` |
| 每月 1 日 04:00 | 6 月 | 同上，路径 `monthly/` |

> 当前 cron 未配置；运维同学手工跑 [scripts/backup.sh](../../../scripts/backup.sh)（如未存在则照下方命令建）。

```bash
#!/usr/bin/env bash
set -euo pipefail
TS=$(date +%Y%m%d-%H%M)
BACKUP_DIR=/var/backups/botgroup/daily
mkdir -p "$BACKUP_DIR"
docker exec botgroup-postgres pg_dump -U botgroup -d botgroup -Fc \
  > "$BACKUP_DIR/botgroup-${TS}.dump"
# 清理 7 天前
find "$BACKUP_DIR" -name 'botgroup-*.dump' -mtime +7 -delete
```

注册：

```bash
# crontab -e
0 2 * * *  /opt/botgroup/scripts/backup.sh
0 3 * * 0  /opt/botgroup/scripts/backup.sh weekly
0 4 1 * *  /opt/botgroup/scripts/backup.sh monthly
```

## 2. 恢复

```bash
# 停后端（避免写冲突）
docker compose stop backend frontend

# 恢复
cat /var/backups/botgroup/daily/botgroup-20260920-020000.dump | \
  docker exec -i botgroup-postgres pg_restore -U botgroup -d botgroup --clean --if-exists

# 起服务
docker compose start backend frontend
```

## 3. 验证

恢复后跑 smoke-test（[smoke-test.md](smoke-test.md)）。