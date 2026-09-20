# KB 重命名（PATCH /api/kb/{kb_id}）

> 实现记录 — commit `ae0bae1` "feat(kb): 知识库列表页支持重命名"

---

## 1. 动机

`/knowledge` 列表只支持新建 + 删除 KB。要改名字只能"删除 → 重建"，文档/chunks 全部陪葬，用户体验差。

## 2. 设计

### 2.1 后端

新增 `PATCH /api/kb/{kb_id}`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | str \| None | 可选；trim 后空 → 422 |
| `description` | str \| None | schema 留位（暂不写入） |
| `is_public` | bool \| None | schema 留位（暂不写入） |

- 复用 `_resolve_kb` + `_can_modify`（owner 或 admin）
- 空 body → 400（防存活探测滥用）
- 写入成功后 audit `action="kb.update"` + 改动 dict

### 2.2 前端

- `api.updateKb(kbId, body)` 包装
- KB 卡片新增"重命名"按钮（删除按钮左侧）
- 弹窗 Dialog：单 Input + Enter 提交 + 错误内联

## 3. 测试

端到端验证（实际 curl）：

```
1. admin 登录（POST /api/auth/login）          200
2. PATCH /api/kb/{id}  {"name":"新名"}          200 + 新名回显
3. PATCH /api/kb/{id}  {"name":"   "}          422
4. PATCH /api/kb/{id}  {}                      400
5. PATCH /api/kb/nonexistent                   404
```

## 4. 不做的事

- `description` / `is_public` 已在 schema 留位，**服务端刻意忽略**——等 UI 加上再放开，避免被"静默成功"的请求骗到。
- KB 重命名不影响 `public_id`（外部挂载链接稳定）。
- 没有"批量重命名"——单文件行为已经够。