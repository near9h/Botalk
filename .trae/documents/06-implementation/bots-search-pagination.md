# 机器人列表搜索 + 分页

> 实现记录 — commit `6756b4b` "feat(bots): 添加机器人下拉支持搜索 + 翻页"

---

## 1. 动机

`/bots` 页面机器人数量到 10+ 后无法管理；下拉选机器人入群时也找不到。

## 2. 变更

### 2.1 后端

`GET /api/bots`：

| 参数 | 作用 |
| --- | --- |
| `q` | 模糊匹配 `name` / `persona` / `model` |
| `limit` | 默认 50，上限 200 |
| `offset` | 偏移 |

响应头加 `X-Total-Count`，前端 Select 拉第二页用。

注意：`Response` 形参必须排在 `Depends` 之前（否则 Python 语法报错）。

### 2.2 前端

`components/ui.tsx` 的 `Select` 扩展为分页模式（`fetchPage` + `labelOf`），驱动搜索下拉：
- 输入即搜（debounce 300ms）
- 滚到底加载下一页
- 高亮匹配项

## 3. 测试

- `curl '/api/bots?q=gpt&limit=5'` → 5 条 + `X-Total-Count`
- `curl '/api/bots?limit=2&offset=2'` → 第 3-4 条