"""Detect the language of a user prompt.

The bot's `persona` is fixed-language (it's authored by a human admin and
stored verbatim in `bots.persona`). When the user types in English but the
persona is Chinese, the model has no signal to switch — and just answers in
Chinese, the persona language. That is bad UX.

We solve it on the prompt side: detect the language of the user's last
message and inject an explicit `[回复语言]` directive into the system
prompt so the model matches the user's language regardless of persona.

Why heuristics and not an LLM call:

  * one extra LLM call per run adds latency + cost on every turn;
  * the signal is local — it's all in the bytes of the input;
  * a 30% character-class threshold is good enough for the practical
    cases (Chinese, English, mixed Chinese-English code-switching);
  * pure Japanese / Korean detection isn't required for the current user
    base, and the heuristic degrades gracefully: those messages fall into
    the "non-Chinese" bucket and the directive just says "non-Chinese".

Cost: zero. One pass over a short string (<= a few hundred chars usually).
"""
from __future__ import annotations

import re

# CJK Unified Ideographs (the bulk of 简繁韩日文), Hiragana, Katakana.
# \u3400-\u9fff covers Unified Ideographs Extension A through CJK Unified
# Ideographs, i.e. essentially "anything that looks like a CJK character".
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
# ASCII letters are good enough as the "looks Latin" signal for English;
# we don't try to discriminate between fr/de/etc. — they all route to the
# same "non-Chinese" bucket, which is what we want.
_LATIN_RE = re.compile(r"[A-Za-z]")


def detect_response_language(
    text: str | None,
    *,
    chinese_threshold: float = 0.30,
    latin_floor: int = 4,
) -> str:
    """Return "zh" if the text is dominantly Chinese, else "en".

    `chinese_threshold` is the share of CJK characters among all
    alphanumeric characters (CJK + ASCII letters). We don't weight digits,
    spaces, or punctuation, because:

      * digits + punctuation are language-agnostic;
      * "你好1" should still count as Chinese.

    The Latin side uses a *floor* instead of a threshold: a single "OK"
    after a Chinese sentence shouldn't flip the answer language, but
    "hi" alone is enough Latin to say "the user is in English mode". 4
    Latin characters roughly matches a single short word.

    Empty / whitespace-only text returns "zh" so we never change behavior
    when there's nothing to inspect (the persona's language wins).
    """
    if not text:
        return "zh"
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if cjk == 0 and latin == 0:
        return "zh"
    if cjk == 0:
        # No CJK at all — assume non-Chinese if there's a word worth,
        # else default to persona's language.
        return "en" if latin >= latin_floor else "zh"
    # "Other candidates" for Chinese: Latin > 0 is fine, model can still
    # answer in Chinese. We only flip to English when CJK is *clearly*
    # outnumbered.
    if cjk / (cjk + latin) >= chinese_threshold:
        return "zh"
    # CJK present but rare → the user is mostly writing in a Latin
    # script (mixed query, English with a single CJK term). Flip to en.
    return "en"