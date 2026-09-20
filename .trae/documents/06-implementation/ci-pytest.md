# CI 接入 pytest

> 实现记录 — commit `f343a29` "ci: 接入 pytest"

---

## 1. 动机

之前 PR 合并靠人工；PMP 质量管理要求至少跑测试 + 类型检查。

## 2. 变更

`.github/workflows/ci.yml` 拆两步：

| Step | 工具 | 命令 |
| --- | --- | --- |
| backend-test | pytest | `cd backend && pip install -e .[test] && pytest -q` |
| frontend-check | tsc | `cd frontend && npm ci && ./node_modules/.bin/tsc --noEmit` |

- 数据库测试用 `postgresql+asyncpg://botgroup:botgroup@localhost:5432/botgroup_test`（CI 内 ephemeral）
- alembic 跑测试环境前先 upgrade head

## 3. 现状

`backend/tests/` 现有 6+ 套：language_detect / msghub_lang_directive / citation_aligner / audit / max_tokens_budget / ...

## 4. 后续

- 加 coverage 上传
- 加前端 lint（ESLint）