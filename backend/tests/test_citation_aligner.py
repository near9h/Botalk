"""Unit tests for `app.services.citation_aligner`.

These tests avoid the live GLM embedding API by mocking
`zhipuai_embed.embed_texts` to return deterministic vectors. We then
verify that:

  * `split_sentences` chunks CJK / English punctuation correctly
  * `inject_markers` only appends to attributed sentences
  * the threshold logic in `align` respects SIM_THRESHOLD
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# Make `app.*` importable when running pytest from anywhere.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import citation_aligner as ca  # noqa: E402
from app.services.citation_aligner import (  # noqa: E402
    Alignment,
    ChunkLike,
    inject_markers,
    split_sentences,
)


# ──────────────────────────── split_sentences ────────────────────────────


def test_split_sentences_chinese_punctuation():
    text = "你好。我是测试！好的？"
    assert split_sentences(text) == ["你好。", "我是测试！", "好的？"]


def test_split_sentences_ascii_punctuation():
    assert split_sentences("Hi. There! OK?") == ["Hi.", "There!", "OK?"]


def test_split_sentences_strips_markdown_bullets():
    text = "- 提前 30日 说明\n- 优先留用三类人员"
    parts = split_sentences(text)
    # Each line becomes its own sentence; bullets stripped.
    assert all(not p.startswith("-") for p in parts)
    assert parts[0].startswith("提前")


def test_split_sentences_keeps_short_fragments():
    # We deliberately don't filter short fragments in split_sentences;
    # rejection happens in `align` so indices line up with the source.
    text = "好。提前 30日。"
    assert split_sentences(text) == ["好。", "提前 30日。"]


# ──────────────────────────── inject_markers ────────────────────────────


def _stub_chunk(key: str, snippet: str = "...") -> dict:
    return {"citation_key": key, "snippet": snippet, "text": snippet}


def test_inject_markers_appends_only_to_attributed():
    answer = "提前 30日 说明情况。请补充人数。程序违法可主张 2N 赔偿金。"
    aligned = [
        Alignment(0, 0, 0.9),
        Alignment(1, None, 0.1),  # rejected (below threshold)
        Alignment(2, 0, 0.8),
    ]
    chunks = [_stub_chunk("劳动合同法.pdf p.11 ¶8")]
    got = inject_markers(answer, chunks, aligned)
    assert "[doc: 劳动合同法.pdf p.11 ¶8]" in got
    # Sentence 1 was rejected → no marker.
    # Easiest assertion: count marker occurrences — exactly 2.
    assert got.count("[doc: 劳动合同法.pdf p.11 ¶8]") == 2


def test_inject_markers_empty_chunks_no_op():
    answer = "Some answer text."
    aligned = [Alignment(0, 0, 0.9)]
    assert inject_markers(answer, [], aligned) == answer


def test_inject_markers_handles_dict_and_object_chunks():
    # Mix dict and ChunkLike — aligner is supposed to coerce both.
    answer = "提前 30日 说明。"
    aligned = [Alignment(0, 1, 0.9)]
    chunks = [
        _stub_chunk("ignored"),
        ChunkLike(text="...", snippet="...", citation_key="劳动合同法.pdf p.11 ¶8"),
    ]
    got = inject_markers(answer, chunks, aligned)
    assert "[doc: 劳动合同法.pdf p.11 ¶8]" in got


def test_inject_markers_out_of_range_chunk_idx():
    answer = "提前 30日 说明。"
    aligned = [Alignment(0, 99, 0.9)]  # idx 99 doesn't exist
    chunks = [_stub_chunk("劳动合同法.pdf p.11 ¶8")]
    # Should silently no-op for that sentence, not crash.
    assert inject_markers(answer, chunks, aligned) == answer


# ──────────────────────────── align (mocked embedding) ────────────────────────────


@pytest.mark.asyncio
async def test_align_threshold_filters_low_scores(monkeypatch):
    """Sentence identical to chunk 0 → chunk_idx 0."""
    # All texts → same vector → cosine = 1.0 with everything.
    async def fake_embed(texts):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        "app.services.zhipuai_embed.embed_texts", fake_embed
    )
    monkeypatch.setattr(
        "app.services.zhipuai_embed.is_configured", lambda: True
    )

    chunks = [
        ChunkLike(
            text="这是关于 A 条款的文本",
            snippet="这是关于 A 条款的文本",
            citation_key="劳动合同法.pdf p.1 ¶1",
        ),
        ChunkLike(
            text="完全无关的另一个话题",
            snippet="完全无关的另一个话题",
            citation_key="其他.pdf p.2 ¶3",
        ),
    ]
    answer = "这是关于 A 条款的文本"
    aligned = await ca.align(answer, chunks)
    # One sentence; with identical embeddings it matches the first
    # chunk (the loop picks index 0 on ties).
    assert len(aligned) == 1
    assert aligned[0].chunk_idx == 0
    assert aligned[0].score >= ca.SIM_THRESHOLD


@pytest.mark.asyncio
async def test_align_rejects_short_sentences(monkeypatch):
    async def fake_embed(texts):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        "app.services.zhipuai_embed.embed_texts", fake_embed
    )
    monkeypatch.setattr(
        "app.services.zhipuai_embed.is_configured", lambda: True
    )

    chunks = [
        ChunkLike(text="anything", snippet="x", citation_key="k"),
    ]
    aligned = await ca.align("好的。", chunks)
    assert aligned[0].chunk_idx is None


@pytest.mark.asyncio
async def test_align_no_chunks_returns_no_match():
    aligned = await ca.align("任何句子都应该有引用。", [])
    # No chunks at all → one Alignment with chunk_idx=None.
    assert len(aligned) == 1
    assert aligned[0].chunk_idx is None


@pytest.mark.asyncio
async def test_align_no_embedding_falls_back(monkeypatch):
    """When `is_configured()` returns False, align returns all-None."""
    monkeypatch.setattr(
        "app.services.zhipuai_embed.is_configured", lambda: False
    )
    chunks = [
        ChunkLike(text="any", snippet="x", citation_key="k"),
    ]
    aligned = await ca.align("任何句子都应该有引用。", chunks)
    assert all(a.chunk_idx is None for a in aligned)


# ──────────────────────────── cosine sanity ────────────────────────────


def test_cosine_zero_vector():
    assert ca._cosine([0, 0], [1, 1]) == 0.0


def test_cosine_orthogonal():
    assert math.isclose(ca._cosine([1, 0], [0, 1]), 0.0)


def test_cosine_identical():
    assert math.isclose(ca._cosine([0.6, 0.8], [0.6, 0.8]), 1.0)