"""`run_group_discussion` 启动 max_tokens 预算的单元测试。

只测分支选择本身：用 monkeypatch 替换掉底层的 `_generate_agent`，避免真的打
LLM，又能拿到实际拼好的 `params["max_tokens"]。CI 没接 pytest，文件末尾保留
`__main__` 自跑入口。
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestrator import msghub  # noqa: E402


@dataclass
class FakeBot:
    id: int
    name: str
    model: str = "MiniMax-M3"
    temperature: float = 0.7
    persona: str = "（测试 persona）"
    skills: list[dict] = field(default_factory=list)


def _bot(i: int, n: str, skills: list[dict] | None = None) -> FakeBot:
    return FakeBot(id=i, name=n, skills=list(skills or []))


async def _run(bot: FakeBot, user_prompt: str) -> int:
    """跑一遍 `_generate_agent`，拦截实际 OpenAI 调用，捕获 params["max_tokens"]。

    用一个会 raise 的占位 OpenAI 客户端，捕获到 params 后直接退出。
    """
    captured: dict = {}

    class _CapturingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def chat(self):  # pragma: no cover
            raise RuntimeError("unreachable")

    class _StubSDK:
        async def create(self, **kwargs):
            captured["params"] = kwargs
            raise _Stop()

    class _Stop(Exception):
        pass

    monkey = msghub  # for read access
    orig = monkey._generate_agent
    # 直接调用其内部分支方法不好做（要 events protocol），改走更简单的：
    # 拦截 AsyncOpenAI.chat.completions.create。
    import openai  # noqa: F401

    real_create = openai.AsyncOpenAI.chat.__class__  # placeholder

    # 改用 msghub 的内部参数计算：跑一圈 fix-up，把 `_generate_agent` 中
    # 用到的所有「可控制输入」构造好，再用 monkey-patched 的 client 看 params。
    from app.db.models import Bot as _BotModel

    # 不通过 SQLAlchemy，直接给 _generate_agent 一个 SQLA-like 对象：
    db_bot = type("B", (), {
        "id": bot.id, "name": bot.name, "model": bot.model,
        "temperature": bot.temperature, "persona": bot.persona,
        "params": {}, "tools": None,
    })()

    # 拦截 openai client.chat.completions.create
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _use(client):
        yield client

    # 最干净的路径：直接在 msghub 内部把 async client.chat.completions.create
    # 替换掉。但 openai SDK 是动态属性。最简单 —— 重写 _message_text 后捕获：
    original_msg_text = msghub._message_text

    def _capture_msg_text(msg):
        # 第一次进来记录 params（caller 用异常的 msg 传进来），其它照常
        if isinstance(msg, _Stop.__class__):
            return ""
        return original_msg_text(msg)

    # 直接改 monkey.client_for，回报一个对象，调用 .chat.completions.create 时记录
    class _FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            raise _Stop()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    msghub.client_for = lambda b: _FakeClient()

    try:
        try:
            await msghub._generate_agent(
                db_bot,  # type: ignore[arg-type]
                history=[{"role": "user", "content": user_prompt}],
                client=_FakeClient(),
                group_members=[bot, _bot(99, "专业写文档")],
                skills=bot.skills,
                user_prompt=user_prompt,
            )
        except _Stop:
            pass
    finally:
        msghub.client_for = orig
    return captured.get("max_tokens")


def test_default_budget_is_2048():
    """普通聊天（不是文档产出），没有 KB 没有 doc-skill：默认 2048。"""
    bot = _bot(1, "甲")
    got = asyncio.run(_run(bot, "你好"))
    assert got == 2048, f"默认应当是 2048，实际 {got}"


def test_html_doc_request_pumps_to_8192():
    """用户明确要求整合 HTML/docx 文档，业务 bot 还没装写文档技能：8192。"""
    bot = _bot(2, "乙")
    got = asyncio.run(_run(bot, "整合一个完整的 html 提案书"))
    assert got == 8192, f"应当 {got}（实际）== 8192"


def test_docx_request_also_pumps_to_8192():
    bot = _bot(3, "丙")
    got = asyncio.run(_run(bot, "请基于上面的意见，整合docx 文件"))
    assert got == 8192


def test_doc_skill_bot_gets_4096():
    """挂上文档写作技能的 bot 一律 4096，不走 deliverable 探测。"""
    bot = _bot(4, "丁", skills=[
        {"key": "write", "manifest": {"instructions": "按模板写", "structured_output": True}}
    ])
    got = asyncio.run(_run(bot, "整合一个完整的 html"))
    assert got == 4096


# ──────────────────────────── 自跑入口（无 pytest） ────────────────────────────


def _run_all() -> int:
    tests = [
        (n, obj) for n, obj in sorted(globals().items())
        if n.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())