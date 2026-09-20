# On-call 手册

> PMBOK § 9.5 / 资源管理 之 运维轮值。

## 1. 轮值表

每周一换；详细表放公司内部 Wiki，这里只放模板。

| 周次 | 主值班 | 备值班 |
| --- | --- | --- |
| W36 | 张三 | 李四 |
| W37 | 李四 | 王五 |
| … | … | … |

## 2. 值班职责

- 5 分钟内响应 P0；30 分钟内响应 P1
- 工作时间内每 4h 看一眼 [incident-response.md](incident-response.md) § 2.1 健康检查命令
- 任何变更（含自己部署）走 [upgrade.md](upgrade.md)
- 任何 P0 完成后写一份 post-mortem（[模板](post-mortem-template.md)）

## 3. 工具箱（常备链接）

- [smoke-test.md](smoke-test.md) — 部署完必跑
- [backup-restore.md](backup-restore.md) — 数据出问题时
- [upgrade.md](upgrade.md) — 升级 / 回滚
- [incident-response.md](incident-response.md) — 应急
- GitHub Actions：仓库 `.github/workflows/ci.yml`

## 4. 交接 checklist

交班时在群里贴：

```
[交班] W37 → W38
- 上周发生：1 次 P2（LLM 超时，自动恢复）
- 当前状态：所有服务 healthy
- 待办：补 KB 描述字段前端
- W38 主值：李四；备值：王五
```