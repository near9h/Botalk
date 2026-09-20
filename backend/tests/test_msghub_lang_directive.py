"""Smoke test: when msghub._generate_agent runs, the system_content it
constructs contains the matching `[回复语言]` / `[Reply language]` directive
based on the user_prompt language.

The test monkey-patches `client.chat.completions.create` so we never
hit the real gateway; we just observe the params that msghub built.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestrator import msghub  # noqa: E402


@dataclass
class _FakeBot:
    id: int
    name: str = "测试bot"
    model: str = "MiniMax-M3"
    temperature: float = 0.7
    persona: str = "你是保险核保专家。"
    params: dict | None = None


class _FakeCompletions:
    def __init__(self, holder):
        self._holder = holder

    async def create(self, **kwargs):
        # 抓 system 消息原文 —— 这是我们要验证的产物
        msgs = kwargs.get("messages", [])
        for m in msgs:
            if m.get("role") == "system":
                self._holder["system"] = m["content"]
                break
        raise _Stop()


class _Stop(Exception):
    pass


class _FakeChat:
    def __init__(self, holder):
        self.completions = _FakeCompletions(holder)


class _FakeClient:
    def __init__(self, holder):
        self.chat = _FakeChat(holder)


async def _capture_system(prompt: str) -> str:
    holder: dict = {}
    msghub.client_for = lambda b: _FakeClient(holder)  # type: ignore[assignment]
    try:
        try:
            await msghub._generate_agent(
                _FakeBot(1),  # type: ignore[arg-type]
                history=[{"role": "user", "content": prompt}],
                client=_FakeClient(holder),
                group_members=[],
                skills=[],
                user_prompt=prompt,
            )
        except _Stop:
            pass
    finally:
        pass
    return holder.get("system", "")


def test_chinese_user_prompt_yields_zh_directive():
    sys_msg = asyncio.run(_capture_system("请帮我看一下这条合同的违约责任"))
    assert "[回复语言]" in sys_msg, sys_msg
    assert "简体中文" in sys_msg, sys_msg
    assert "[Reply language]" not in sys_msg


def test_english_user_prompt_yields_en_directive():
    sys_msg = asyncio.run(_capture_system("Could you please review this clause?"))
    assert "[Reply language]" in sys_msg, sys_msg
    assert "English" in sys_msg
    assert "[回复语言]" not in sys_msg


def test_short_latin_burst_does_not_flip_to_english():
    # "OK" 不应让模型切成英文 —— 阈值 latin_floor=4
    sys_msg = asyncio.run(_capture_system("OK 请继续"))
    assert "[回复语言]" in sys_msg


# ──────────────────────────── 自跑入口 ────────────────────────────


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