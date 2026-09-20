# 06 实现记录（Implementation Records）

> 每个实现类 feature / bugfix 一份"怎么落地的 + 为什么这样落地"的回溯文档。
> 这是 PMP 范围管理 / 知识管理 的产出物，便于审计和回归。

---

## 1. 索引

| 主题 | 文档 | 关联 commit |
| --- | --- | --- |
| 群组策略防火墙 | [group-policy-firewall.md](group-policy-firewall.md) | — |
| 引用稳定（snippet 对齐 + bbox 二次定位） | [citation-stability.md](citation-stability.md) | — |
| 附件生成稳定（大文档分块 + 续接） | [attachment-generation-stability.md](attachment-generation-stability.md) | — |
| 国际化（语言跟随） | [i18n-completion.md](i18n-completion.md) | `8eea475` / `ee78cf1` |
| 机器人搜索 + 分页 | [bots-search-pagination.md](bots-search-pagination.md) | `6756b4b` |
| KB 重命名 | [kb-rename.md](kb-rename.md) | `ae0bae1` |
| CI 接入 pytest | [ci-pytest.md](ci-pytest.md) | `f343a29` |
| HTML 文档渲染 + 上下文注入 + max_tokens 分级 | [history/html-context-budget.md](../history/html-context-budget.md) | `6f2c71f` |

---

## 2. 实现规范（Implementation Conventions）

### 2.1 代码组织

- **每个文件顶部 docstring**：写清"这块代码做什么 + 关键不变量"
- **路由文件**：列在顶部 `Surface area:` 注释里所有端点 + 路径
- **Pydantic schema**：放在对应路由文件顶部（不是全局 `schemas.py`），保证模块可独立读

### 2.2 错误处理

- 路由层：FastAPI `HTTPException` + 业务状态码（4xx 业务 / 5xx 内部）
- Service 层：抛自定义异常，路由层捕获并翻译
- **审计必走** `_audit_ctx` 依赖

### 2.3 数据库

- 模型定义 `db/models.py`；每次 schema 改动先写 Alembic 迁移
- 写操作：`session.add()` → `await session.commit()` → `await session.refresh()`
- 删操作：先校验权限（`require_user` / `require_admin`），后做 cascade

### 2.4 前端

- TypeScript strict
- 所有 fetch 走 `lib/api.ts` 的 `request<T>()` 包装（统一错误 + 凭证）
- 长任务用 SSE，不用 WebSocket

### 2.5 Commit 规范

```
<type>(<scope>): <subject>
```

`type`：`feat / fix / refactor / docs / test / chore`
`scope`：`chat / kb / auth / bots / ci ...`

破坏性变更在 body 里加 `BREAKING:` 前缀。

---

## 3. 待补的实操细节

每份 plan / 报告历史文件迁移过来后**未改内容**；后续在 [history/](../history/) 沉淀原版，本目录放"对照 commit 的精简版"。