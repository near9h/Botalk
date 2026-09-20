# 升级 / 回滚（Upgrade & Rollback）

## 1. 标准升级流程

```bash
cd /opt/botgroup       # 部署根目录
git pull --rebase      # 1) 拉代码
docker compose build backend frontend   # 2) 重建镜像
docker compose up -d                    # 3) 滚动起服务
docker compose logs -f --tail=100 backend   # 4) 看启动日志
```

> **不要** 跨大版本跳过中间 tag。每个 commit 是 idempotent 单元。

## 2. 数据库迁移

backend 启动自动跑 `alembic upgrade head`（看 `entrypoint.sh`）。

> 重要：Alembic 迁移 **向前兼容**，写迁移的人要保证老代码能跑新 schema。

## 3. 回滚

### 3.1 应用回滚

```bash
git log --oneline -10        # 找上一个稳定 commit
git checkout <good-sha>      # 或 git revert HEAD
docker compose build backend frontend
docker compose up -d
```

### 3.2 数据库回滚

```bash
# 先停服务
docker compose stop backend frontend

# 卸到上一个 revision（先确认！）
docker exec botgroup-backend alembic downgrade -1
# 或指定 revision
docker exec botgroup-backend alembic downgrade <rev>
```

### 3.3 灾难恢复（数据坏了）

走 [backup-restore.md](backup-restore.md) § 2 流程。

## 4. 灰度

当前单机单库，不做灰度。后续多副本时再做金丝雀。

## 5. 升级窗口

- 工作日 22:00–次日 02:00（业务低峰）
- 提前在群内通知 "30 分钟后升级"