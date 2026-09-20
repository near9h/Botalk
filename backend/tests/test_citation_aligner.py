"""`app.services.citation_aligner` 的单元测试。

当前实现是「子串匹配」而非早期的「向量相似度」：靠 chunk 文本的前若干字符
在回答里找命中点，再把 `[doc: <key>]` 标记插到下一个句子边界。因此这里只测
纯函数，不碰数据库、网络和 embedding，CI 里可以直接跑。

注意：`pyproject.toml` 还没有 pytest 依赖，CI 也尚未接入 pytest，所以文件末尾
留了一个 `__main__` 自跑入口，`python tests/test_citation_aligner.py` 即可执行
全部用例（两种跑法都支持）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 让 `app.*` 可导入，无论从哪个目录运行。
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.citation_aligner import (  # noqa: E402
    Alignment,
    ChunkLike,
    FINGERPRINT_LEN,
    _bracket_spans,
    _find_outside_spans,
    _fingerprint,
    _normalize,
    _span_end_around,
    _to_chunk_like,
    align,
    inject_markers,
)


def _chunk(key: str, text: str) -> ChunkLike:
    return ChunkLike(text=text, snippet=text, citation_key=key)


# ──────────────────────────── _normalize / _fingerprint ────────────────────────────


def test_normalize_strips_punctuation_and_whitespace():
    # 全角标点、换行、空格都不参与匹配，否则 LLM 的排版漂移会让引用解析失败。
    assert _normalize("你好，\n 世界。") == "你好世界"


def test_normalize_folds_fullwidth_to_halfwidth():
    # NFKC 把全角括号折成半角，所以两种写法归一化后相等。
    assert _normalize("（三）") == _normalize("(三)")


def test_fingerprint_caps_length_and_handles_empty():
    assert _fingerprint("一二三四五", 3) == "一二三"
    assert _fingerprint("", 3) == ""


def test_fingerprint_default_len_is_30():
    long_text = "甲" * 100
    assert len(_fingerprint(long_text)) == FINGERPRINT_LEN


# ──────────────────────────── 方括号区间（锚点安全区） ────────────────────────────


def test_bracket_spans_finds_intervals():
    # 区间含方括号本身，即 `[start, end)`。
    assert _bracket_spans("a[b]c[d]") == [(1, 4), (5, 8)]


def test_bracket_spans_ignores_unclosed_bracket():
    assert _bracket_spans("a[b") == []


def test_span_end_around_only_inside():
    spans = [(1, 3)]
    assert _span_end_around(spans, 2) == 3  # 内部
    assert _span_end_around(spans, 1) is None  # 起点不算内部
    assert _span_end_around(spans, 3) is None  # 终点（']'）不算内部


def test_find_outside_spans_skips_bracket_interior():
    # "x[.].y"：索引 2 的 '.' 落在 [.] 内必须跳过，返回括号外那个（索引 4）。
    assert _find_outside_spans("x[.].y", ".", 0, [(1, 4)]) == 4


# ──────────────────────────── inject_markers ────────────────────────────


def test_inject_markers_inserts_at_sentence_boundary():
    chunks = [_chunk("劳动合同法.pdf p.12 ¶3", "裁减人员时应当优先留用下列人员")]
    answer = "裁减人员时应当优先留用下列人员。后续说明。"
    got = inject_markers(answer, chunks, [])
    assert got == "裁减人员时应当优先留用下列人员。 [doc: 劳动合同法.pdf p.12 ¶3]后续说明。"


def test_inject_markers_no_fingerprint_match_is_noop():
    chunks = [_chunk("劳动合同法.pdf p.12 ¶3", "完全无关的另一段内容")]
    answer = "裁减人员时应当优先留用下列人员。"
    assert inject_markers(answer, chunks, []) == answer


def test_inject_markers_empty_inputs_are_noop():
    answer = "任意回答。"
    assert inject_markers(answer, [], []) == answer
    assert inject_markers("", [_chunk("k", "任意内容")], []) == ""


def test_inject_markers_skips_chunk_without_citation_key():
    chunks = [ChunkLike(text="裁减人员时应当优先留用下列人员", snippet="同上", citation_key="")]
    answer = "裁减人员时应当优先留用下列人员。"
    assert inject_markers(answer, chunks, []) == answer


def test_inject_markers_accepts_dict_and_object_chunks():
    answer = "裁减人员时应当优先留用下列人员。"
    as_dict = {"citation_key": "k.pdf p.1 ¶1", "snippet": "裁减人员时应当优先留用下列人员", "text": ""}
    got_dict = inject_markers(answer, [as_dict], [])
    got_obj = inject_markers(answer, [_chunk("k.pdf p.1 ¶1", "裁减人员时应当优先留用下列人员")], [])
    assert "[doc: k.pdf p.1 ¶1]" in got_dict
    assert got_dict == got_obj


def test_inject_markers_stacks_chunks_hitting_same_anchor():
    shared = "裁减人员时应当优先留用下列人员"
    chunks = [_chunk("a.pdf p.1 ¶1", shared), _chunk("b.pdf p.2 ¶2", shared)]
    got = inject_markers(shared + "。", chunks, [])
    assert got.count("[doc:") == 2
    assert "[doc: a.pdf p.1 ¶1]" in got and "[doc: b.pdf p.2 ¶2]" in got


def test_inject_markers_keeps_existing_marker_intact():
    """回归：注入点绝不能落进 LLM 已写的 `[doc: …]` 标记内部。

    citation key 自带 `.` / `?`（`劳动合同法. pdf p. 12 ¶1`），而它们同时又是
    句子终止符。若吸附时不排除方括号内部，注入的标记会插到已有标记中间，产出
    `[doc: A [doc: B] A]` 这种畸形嵌套 —— 前端按第一个 `]` 截断，解析不出 key，
    只能渲染成不可点击的 `?`。这里断言「原标记逐字保留」。
    """
    existing = "[doc: 劳动合同法. pdf p. 12 ¶1]"
    answer = f"裁减人员时应当优先留用下列人员{existing} vs 其他情形"
    chunks = [_chunk("劳动合同法.pdf p.12 ¶3", "裁减人员时应当优先留用下列人员")]
    got = inject_markers(answer, chunks, [])
    assert existing in got, f"已有标记被破坏了：{got}"
    # 两个标记各自独立，不能出现嵌套。
    assert got.count("[doc:") == 2


def test_inject_markers_anchor_escapes_bracket_interior():
    """起点本身就落在标记内部时，锚点必须先跳到标记之后。"""
    existing = "[doc: 劳动合同法. pdf p. 12 ¶1]"
    text = f"前缀{existing}。"
    # 直接把 match_pos 落在方括号内部，验证 _next_anchor 会跳出去。
    from app.services.citation_aligner import _next_anchor

    inside = text.index("劳动合同法")
    anchor = _next_anchor(text, inside)
    assert anchor >= text.index("]") + 1


# ──────────────────────────── align / _to_chunk_like ────────────────────────────


def test_to_chunk_like_skips_none_and_coerces():
    got = _to_chunk_like([None, {"citation_key": "k", "snippet": "s", "text": "t"}])
    assert len(got) == 1
    assert got[0].citation_key == "k"


def test_align_returns_one_stub_per_chunk():
    # 旧版按句返回相似度，现在保留形状但不参与决策：一句一个占位、chunk_idx 为 None。
    chunks = [_chunk("a", "x"), _chunk("b", "y")]
    got = align("任意回答。", chunks)
    assert len(got) == 2
    assert all(isinstance(a, Alignment) and a.chunk_idx is None for a in got)


def test_align_empty_chunks_returns_empty():
    assert align("任意回答。", []) == []


# ──────────────────────────── 自跑入口（无 pytest 依赖） ────────────────────────────


def _run_all() -> int:
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
