# backend/app/skills

> 技能注册中心（`registry.py`）。详见 [.trae/documents/04-architecture/skill-center.md](../../../.trae/documents/04-architecture/skill-center.md)。

## 文件

- `registry.py` — 启动时 idempotent 写入内置技能

## 内置技能

按需扩展；当前含：

- `web_search`（占位）
- `kb_query`（检索知识库）
- `attach_doc`（附件生成）

## 接入新技能

1. 在 `registry.py` 注册
2. 在 `tools/` 加实现
3. 更新 `/api/skills` schema
5. 提交 + CI