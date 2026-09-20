"""Unit tests for the sentence-window context stitcher.

Pure-Python tests for ``stitch_text``; async tests for ``fetch_window``
use SQLAlchemy's mock session so we exercise the SQL building without
needing a live Postgres.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.sentence_window import (  # noqa: E402
    fetch_window,
    stitch_text,
)


# ──────────────────────────── stitch_text ────────────────────────────


def test_stitch_empty_returns_empty():
    assert stitch_text([]) == ""


def test_stitch_single_chunk():
    assert stitch_text([{"text": "hello"}]) == "hello"


def test_stitch_joins_with_double_newline_in_order():
    chunks = [{"text": "alpha"}, {"text": "beta"}, {"text": "gamma"}]
    assert stitch_text(chunks) == "alpha\n\nbeta\n\ngamma"


def test_stitch_skips_empty_text():
    chunks = [{"text": ""}, {"text": "only"}, {"text": None}]
    assert stitch_text(chunks) == "only"


def test_stitch_strips_whitespace_per_chunk():
    chunks = [{"text": "  hello  "}, {"text": "\nworld\n"}]
    assert stitch_text(chunks) == "hello\n\nworld"


# ──────────────────────────── fetch_window (async) ────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal stand-in for AsyncSession that records the SQL kwargs
    and returns canned rows for ``fetch_window``."""

    def __init__(self, rows):
        self.rows = rows
        self.calls: list[dict] = []

    async def execute(self, _stmt, params):
        self.calls.append({"params": dict(params)})
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_fetch_window_returns_siblings_in_para_order():
    rows = [
        {"id": 1, "para": 2, "text": "prev"},
        {"id": 2, "para": 3, "text": "hit"},
        {"id": 3, "para": 4, "text": "next"},
    ]
    s = _FakeSession(rows)
    out = await fetch_window(s, kb_doc_id=42, page=27, para=3, window=1)
    assert [r["text"] for r in out] == ["prev", "hit", "next"]
    # Window is centred on `para=3`, ±1 → BETWEEN 2 AND 4.
    call = s.calls[0]["params"]
    assert call["doc_id"] == 42
    assert call["page"] == 27
    assert call["lo"] == 2
    assert call["hi"] == 4


@pytest.mark.asyncio
async def test_fetch_window_window_zero_short_circuits():
    s = _FakeSession([])
    out = await fetch_window(s, kb_doc_id=1, page=1, para=1, window=0)
    assert out == []
    assert s.calls == []  # no SQL issued


@pytest.mark.asyncio
async def test_fetch_window_missing_page_short_circuits():
    """PDFs without page numbers (Excel / FAQ) used to pass page=None
    all the way down; we shouldn't blow up trying to BETWEEN on NULL."""
    s = _FakeSession([])
    out = await fetch_window(s, kb_doc_id=1, page=None, para=5, window=1)
    assert out == []
    assert s.calls == []


@pytest.mark.asyncio
async def test_fetch_window_sparse_para_still_works():
    """MinerU sometimes skips whitespace blocks so consecutive `para`
    values can skip (e.g. 1, 3, 5). The BETWEEN inclusive range still
    returns whatever's in range — we don't require contiguous paras."""
    rows = [
        {"id": 1, "para": 3, "text": "a"},
        {"id": 2, "para": 5, "text": "b"},
    ]
    s = _FakeSession(rows)
    out = await fetch_window(s, kb_doc_id=42, page=27, para=3, window=2)
    assert len(out) == 2
    # lo=1, hi=5 — sparse para=2,4 are just absent.
    assert s.calls[0]["params"]["lo"] == 1
    assert s.calls[0]["params"]["hi"] == 5


@pytest.mark.asyncio
async def test_fetch_window_handles_dict_row_shape():
    """Real SQLAlchemy mapping rows are dict-like; our helper converts
    each row to a plain dict. The simplest stand-in is a plain dict."""
    rows = [
        {"id": 1, "para": 2, "text": "x", "snippet": "x",
         "bbox_json": None, "ragflow_chunk_id": None,
         "embedding_model": None, "kb_doc_id": 42, "page": 27},
    ]
    s = _FakeSession(rows)
    out = await fetch_window(s, kb_doc_id=42, page=27, para=2, window=1)
    assert len(out) == 1
    assert out[0]["text"] == "x"
    assert out[0]["para"] == 2


# ──────────────────────────── integration: stitch after fetch ─────


@pytest.mark.asyncio
async def test_full_pipeline_hit_content_replaced_bbox_untouched():
    """End-to-end simulation: a hit gets its `content` replaced by the
    stitched text but its bbox / citation_key remain on the original
    hit — that's how PDF highlights stay precise."""
    hit = {
        "chunk_id": 99,
        "kb_doc_id": 42,
        "page": 27,
        "para": 3,
        "content": "Referral to SPC / Treaty is required.",
        "bbox": [100.0, 200.0, 300.0, 220.0],
        "citation_key": "Risk.pdf p.27 ¶3",
        "match_source": "bm25",
    }
    siblings_rows = [
        {"text": "Referral triggers above S$1m:"},
        {"text": "Referral to SPC / Treaty is required."},  # the hit
        {"text": "Submit via Special Acceptance Form."},
    ]
    s = _FakeSession(siblings_rows)
    fetched = await fetch_window(
        s, kb_doc_id=hit["kb_doc_id"], page=hit["page"],
        para=hit["para"], window=1,
    )
    assert len(fetched) == 3
    # Mutate the hit as `retrieve()` would.
    hit["content"] = stitch_text(fetched)
    hit["window_size"] = len(fetched)
    # Verify the hit's surface metadata is untouched.
    assert hit["bbox"] == [100.0, 200.0, 300.0, 220.0]
    assert hit["citation_key"] == "Risk.pdf p.27 ¶3"
    assert hit["chunk_id"] == 99
    # Verify content was stitched and *contains* the original hit's
    # text plus the surrounding context.
    assert "Referral triggers above S$1m:" in hit["content"]
    assert "Referral to SPC / Treaty is required." in hit["content"]
    assert "Submit via Special Acceptance Form." in hit["content"]
    assert hit["window_size"] == 3