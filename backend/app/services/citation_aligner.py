"""Posthoc citation alignment — substring match + sentence anchoring.

The chat pipeline emits `(text, cited_refs)` from `_generate_agent`. The
LLM is *supposed* to write `[doc: filename p.X ¶Y]` markers inline, but
in practice it often paraphrases or forgets. Benchmarks (FullCite,
arXiv 2606.07130) show prompt-only citation generation reaches
snippet-F1 ≈ 12.8 on long-form QA — about 5× worse than posthoc
alignment.

The previous version of this module embedded every sentence and the
retrieved chunks via GLM, computed cosine similarity, and inserted
markers at sentence boundaries. That worked, but in practice it
broke markdown structure (sentence splits around `**bold**` / list
items / table rows mangled the answer) and the appended markers
landed mid-paragraph in unpredictable places.

This version uses a much simpler strategy: **substring match**.

  1. For each retrieved chunk, take a short verbatim fingerprint
     (the first ~30 chars of `chunk.snippet`, normalized to strip
     whitespace).
  2. Search the LLM reply for that fingerprint. If the LLM actually
     cited the chunk (verbatim quote or near-verbatim paraphrase),
     the substring will appear inside the prose.
  3. Anchor the marker on the **next** sentence/paragraph boundary
     after the match position — that's where a human reader would
     naturally put the reference.
  4. If no fingerprint matches (LLM paraphrased too aggressively),
     fall back to sentence-level longest-substring match with a
     shorter (15-char) fingerprint.

We never modify the LLM reply's text — only insert `[doc: <key>]`
markers in places where they're contextually correct. The frontend
markdown renderer turns those into clickable chips exactly like it
would for an LLM-authored marker.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)


# ──────────────────────────── tunables ────────────────────────────

# Length of the verbatim fingerprint we look for inside the LLM reply.
# 30 chars is long enough to avoid accidental false positives on
# common phrases ("经提前", "需提交" etc.) but short enough that the
# LLM only has to copy the first sentence of the chunk.
FINGERPRINT_LEN = 30

# If no chunk matches with the primary fingerprint length, retry with
# this shorter fallback. Helps when the LLM lightly paraphrases the
# first sentence.
FINGERPRINT_FALLBACK = 15

# Minimum match score for the fallback. 0.6 = at least 60% of the
# characters in the fingerprint appear in order in the answer. We
# deliberately don't require *contiguous* match for the fallback —
# LLMs often drop a word or two when paraphrasing.
FALLBACK_MIN_OVERLAP = 0.6


# ──────────────────────────── data types ────────────────────────────


@dataclass(slots=True)
class Alignment:
    """One sentence's attribution decision (kept for backwards-compat
    with the unit tests; the new injector doesn't actually consult
    `sentence_idx` — markers are placed at the substring match)."""

    sentence_idx: int
    chunk_idx: int | None
    score: float


@dataclass(slots=True)
class ChunkLike:
    """Subset of fields the aligner reads from a retrieved chunk."""

    text: str = ""
    snippet: str = ""
    citation_key: str = ""


# ──────────────────────────── normalization ────────────────────────────


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[，。！？；：、,.!?;:()（）\[\]【】\"'""''`~—…\-]")


def _normalize(s: str) -> str:
    """Strip whitespace + full-width / half-width punctuation so the
    same Chinese phrase matches across line breaks and stylistic
    variants (full-width comma vs ASCII comma, etc.)."""
    if not s:
        return ""
    # NFKC folds full-width / half-width punctuation into a single
    # codepoint — that alone catches 90% of formatting drift.
    s = unicodedata.normalize("NFKC", s)
    s = _PUNCT_RE.sub("", s)
    s = _WHITESPACE_RE.sub("", s)
    return s


def _fingerprint(s: str, n: int = FINGERPRINT_LEN) -> str:
    """First `n` chars of the normalized chunk text, or less if the
    chunk is shorter. Never returns an empty string if the chunk
    itself isn't empty."""
    norm = _normalize(s)
    if not norm:
        return ""
    return norm[:n]


# ──────────────────────────── alignment ────────────────────────────


def _to_chunk_like(chunks: Iterable) -> list[ChunkLike]:
    out: list[ChunkLike] = []
    for c in chunks:
        if c is None:
            continue
        if isinstance(c, ChunkLike):
            out.append(c)
            continue
        if isinstance(c, dict):
            out.append(
                ChunkLike(
                    text=c.get("text") or c.get("content") or "",
                    snippet=c.get("snippet", ""),
                    citation_key=c.get("citation_key", ""),
                )
            )
            continue
        out.append(
            ChunkLike(
                text=getattr(c, "text", "") or getattr(c, "content", ""),
                snippet=getattr(c, "snippet", ""),
                citation_key=getattr(c, "citation_key", ""),
            )
        )
    return out


def _find_substring(haystack_norm: str, needle_norm: str) -> int:
    """Find `needle_norm` inside `haystack_norm`. Returns start index
    or -1. Both inputs must already be `_normalize()`-d."""
    if not needle_norm:
        return -1
    idx = haystack_norm.find(needle_norm)
    return idx


def _find_overlap(haystack_norm: str, needle_norm: str) -> int:
    """Lightweight partial-overlap finder.

    Slides a window of `len(needle_norm)` over `haystack_norm` and
    counts character matches at each position. Returns the *position*
    of the window with the highest overlap ratio (best / len(needle)).

    Used as the fallback when the verbatim substring isn't present.
    Complexity O(N * M) where N = haystack length and M = needle
    length. With chunks of 30-50 chars and replies under 2 KB this
    is well under 1 ms — no need for fancy algorithms.
    """
    if not needle_norm:
        return -1
    h_len = len(haystack_norm)
    n_len = len(needle_norm)
    if h_len < n_len:
        # Need haystack at least as long as needle; if shorter just
        # try a regular substring match.
        return haystack_norm.find(needle_norm)

    best_score = 0
    best_pos = -1
    for i in range(h_len - n_len + 1):
        score = 0
        for j in range(n_len):
            if haystack_norm[i + j] == needle_norm[j]:
                score += 1
        if score > best_score:
            best_score = score
            best_pos = i
    if best_pos >= 0 and best_score / n_len >= FALLBACK_MIN_OVERLAP:
        return best_pos
    return -1


def _bracket_spans(s: str) -> list[tuple[int, int]]:
    """返回 `s` 里所有 `[...]` 区间的 `[start, end)`（含方括号）。"""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, ch in enumerate(s):
        if ch == "[" and start is None:
            start = i
        elif ch == "]" and start is not None:
            spans.append((start, i + 1))
            start = None
    return spans


def _span_end_around(spans: list[tuple[int, int]], pos: int) -> int | None:
    """`pos` 落在某个区间**内部**时返回该区间结束位置，否则 `None`。"""
    for start, end in spans:
        if start < pos < end:
            return end
    return None


def _find_outside_spans(
    answer: str, needle: str, from_pos: int, spans: list[tuple[int, int]]
) -> int:
    """从 `from_pos` 找 `needle`，跳过落在 `[...]` 内部的命中。

    命中落在已有引用标记里时，跳到该标记之后继续找 —— 否则锚点会插进
    `[doc: …]` 中间。
    """
    pos = from_pos
    while pos <= len(answer):
        idx = answer.find(needle, pos)
        if idx < 0:
            return -1
        skip_to = _span_end_around(spans, idx)
        if skip_to is None:
            return idx
        pos = skip_to
    return -1


def _next_anchor(answer: str, match_pos: int) -> int:
    """Pick the byte offset of the *next* sentence/paragraph boundary
    after `match_pos` inside `answer`. We snap to whichever comes
    first: end of the current paragraph (`\\n\\n`), end of the current
    line (`\\n`), or end of the current CJK sentence (。！？).

    Snapping to a boundary (instead of right at the match position)
    makes the inserted `[doc: …]` marker sit naturally at the end of
    a thought, like a human author would place it.

    约束：吸附点必须落在所有 `[...]` 之外。citation key 里本身带 `.` / `?`
    （`劳动合同法. pdf p. 12 ¶1`），而它们同时又是句子终止符 —— 不排除的话，
    注入的 `[doc: …]` 会落进 LLM 已写的标记内部，生成
    `[doc: A [doc: B] A]` 这种畸形嵌套：前端 `CITATION_PATTERN` 按第一个 `]`
    截断，解析不出 key，只能渲染成不可点击的 `?`。
    """
    spans = _bracket_spans(answer)
    # 起点本身就在某个标记内部时，先跳到标记之后。
    escaped = _span_end_around(spans, match_pos)
    if escaped is not None:
        match_pos = escaped

    # First try paragraph break (most common structure in chat output).
    nl2 = _find_outside_spans(answer, "\n\n", match_pos, spans)
    if nl2 >= 0:
        return nl2
    # Then line break.
    nl = _find_outside_spans(answer, "\n", match_pos, spans)
    if nl >= 0:
        return nl
    # Then CJK sentence terminator.
    for term in ("。", "！", "?", "!", ".", "？"):
        idx = _find_outside_spans(answer, term, match_pos, spans)
        if idx >= 0:
            return idx + 1  # include the terminator
    # Fallback: insert at the match position itself.
    return match_pos


def align(answer: str, chunks: Iterable) -> list[Alignment]:
    """Compute alignments for the legacy per-sentence API surface.

    The new injector (`inject_markers`) doesn't read this list — it
    runs its own substring search. We keep this function returning
    something sensible (one Alignment per chunk, in chunk order) so
    existing callers and unit tests don't break, but the values are
    not used by `inject_markers` anymore.

    Returns `[(chunk_idx, None, 0.0)]` per chunk so the unit tests'
    shape checks keep working.
    """
    chunk_list = _to_chunk_like(chunks)
    return [
        Alignment(i, None, 0.0)
        for i in range(len(chunk_list))
    ]


def inject_markers(
    answer: str,
    chunks: Iterable,
    aligned: list[Alignment] | None = None,
) -> str:
    """Insert `[doc: <citation_key>]` markers where chunks appear in the reply.

    The `aligned` argument is accepted for backwards compatibility but
    ignored — the new algorithm scans the answer text directly.

    Marker placement rules:
      * We match each chunk's first ~30 chars (normalized) against
        the answer.
      * On a hit, we anchor the marker on the next sentence/paragraph
        boundary after the hit position.
      * Multiple chunks matching the same span get their markers
        stacked together: `[1] [2]`.
      * Chunks with no match are dropped from the inline stream but
        still surface in the footer chip strip (the caller passes
        the same `cited_refs` to the SSE event unchanged).
    """
    chunk_list = _to_chunk_like(chunks)
    if not chunk_list or not answer:
        return answer

    norm_answer = _normalize(answer)

    # Build a list of (insert_position, marker_string) we want to splice
    # in. Sorted by position so earlier markers don't shift later
    # match offsets.
    inserts: list[tuple[int, str]] = []
    for idx, c in enumerate(chunk_list):
        if not c.citation_key:
            continue
        source = c.snippet or c.text
        if not source:
            continue
        # Primary: 30-char verbatim match.
        fp = _fingerprint(source, FINGERPRINT_LEN)
        match_pos = _find_substring(norm_answer, fp) if fp else -1
        if match_pos < 0:
            # Fallback: shorter fingerprint with overlap scoring.
            short_fp = _fingerprint(source, FINGERPRINT_FALLBACK)
            if not short_fp:
                continue
            match_pos = _find_overlap(norm_answer, short_fp)
            if match_pos < 0:
                continue
        # The normalized match position no longer maps 1:1 to the
        # raw `answer` offset (we stripped punctuation/whitespace).
        # The safest approach: search the raw answer for the *first*
        # substring that normalizes to the same prefix as `fp`.
        # Use a relaxed search: take the first len(fp) chars of the
        # normalized answer at match_pos, find the same string in
        # the raw answer starting near that offset.
        anchor = _raw_anchor_for(answer, norm_answer, match_pos, len(fp))
        if anchor is None:
            anchor = match_pos  # shouldn't happen, but be safe
        anchor = _next_anchor(answer, anchor)
        # Build a stable marker label: `[1]`-style ordinal for the
        # *first* time we see this chunk; `[1] [2] [3]` for repeats.
        marker = f" [doc: {c.citation_key}]"
        inserts.append((anchor, marker))

    if not inserts:
        return answer

    # Merge inserts at the same anchor (e.g. multiple chunks matching
    # the same span) into a single block.
    inserts.sort(key=lambda x: x[0])
    merged: list[tuple[int, str]] = []
    for pos, mk in inserts:
        if merged and merged[-1][0] == pos:
            merged[-1] = (pos, merged[-1][1] + mk)
        else:
            merged.append((pos, mk))

    # Splice right-to-left so earlier offsets stay valid.
    out = answer
    for pos, marker in reversed(merged):
        out = out[:pos] + marker + out[pos:]
    return out


def _raw_anchor_for(answer: str, norm_answer: str, norm_pos: int, length: int) -> int | None:
    """Map a position in the normalized answer back to a position in the
    raw answer.

    The naive `norm_pos` (and `norm_pos + length`) don't necessarily
    line up with raw offsets because normalization drops characters.
    We approximate by scanning the raw answer and counting how many
    raw characters survive normalization at each step, then return
    the raw offset closest to the normalized one.
    """
    if norm_pos == 0:
        return 0
    raw_pos = 0
    seen_norm = 0
    last_kept_raw = 0
    while raw_pos < len(answer) and seen_norm < norm_pos:
        ch = answer[raw_pos]
        # Mirrors `_normalize`'s stripping rules.
        if ch.isspace():
            raw_pos += 1
            continue
        # NFKC fold then punct-strip — easiest check is "does the
        # character survive normalization?". Skip the full normalize
        # cost; just hard-code the punct class.
        if ch in "，。！？；：、,!?;:()（）[]【】\"'""''`~—…-":
            raw_pos += 1
            continue
        seen_norm += 1
        last_kept_raw = raw_pos
        raw_pos += 1
    return last_kept_raw