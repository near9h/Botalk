# backend/app/tools

> bot 可调用工具（tool-use 协议）。当前由 `app/skills` 间接调用。

每个工具 = 一个独立 Python 文件，提供：

- `name: str`
- `description: str`
- `parameters: dict`（JSON Schema）
- `async def run(...) -> Any`

新增工具的流程：

1. 本目录新增文件
2. 在 `app/skills/registry.py` 注册
3. 在 `app/api/skills.py` 暴露 schema