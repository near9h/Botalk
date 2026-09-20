"""Unit tests for `app.services.language_detect`.

The detector is a pure-function heuristic, so no DB / network involved.
These tests lock in the practical cases that the bot reply-language
directive depends on.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.language_detect import detect_response_language  # noqa: E402


def test_empty_or_whitespace_defaults_to_zh():
    assert detect_response_language("") == "zh"
    assert detect_response_language(None) == "zh"
    assert detect_response_language("   \n  ") == "zh"


def test_pure_chinese_is_zh():
    s = "请帮我看一下这条合同的违约责任条款"
    assert detect_response_language(s) == "zh"


def test_pure_english_is_en():
    # 单个短词不算英文（floor=4）。这里给一个完整短句。
    s = "Could you please review the contract clause?"
    assert detect_response_language(s) == "en"


def test_short_latin_burst_is_zh():
    # 单个 "OK" / "Hi" 不应把语种切到英文 —— 阈值 latin_floor=4。
    assert detect_response_language("OK") == "zh"
    assert detect_response_language("hi 看一下") == "zh"


def test_cjk_dominant_mixed_is_zh():
    # 30% 是 zh/en 的分水岭。中文字符明显多于英文字符时保持中文。
    s = "请帮我看一下 Linux 的 iptables 规则配置"
    assert detect_response_language(s) == "zh"


def test_latin_dominant_with_rare_cjk_is_en():
    # 输入里含 CJK 但占比低 → 视为英文用户。
    s = "How do I configure iptables with NAT rules and inspect 流量 logs?"
    assert detect_response_language(s) == "en"


def test_japanese_only_falls_back_to_zh():
    # Hiragana/Katakana 不在我们覆盖的 CJK 区间里 (\u3040-\u30ff vs
    # \u3400-\u9fff)，所以日文输入会落到「cjk=0 latin=0」分支，按 persona
    # 默认（中文）返回。如果以后要加日文支持，扩展 \u3040-\u30ff 即可。
    s = "これはテストメッセージです"
    assert detect_response_language(s) == "zh"


def test_digits_and_punctuation_alone_default_to_zh():
    # 数字 + 标点不算任何语种的证据 → 保持默认 zh（让 persona 语言胜出）。
    assert detect_response_language("123 456.789 !!!") == "zh"


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