"""Structured report payload schema (路线 B).

The bot no longer emits a free-form markdown document. Instead, the
model's *entire reply* (when it has the `document_writer` skill
enabled) is parsed as a `ReportPayload` JSON object, validated by
Pydantic, and rendered through a Jinja2 template into both an `.html`
and a `.docx` file. The result is reproducible across runs (modulo
LLM nondeterminism) and the visual layout is owned by the template,
not by the LLM.

Why this exists:
- "Same prompt → same file" was impossible when the bot was
  free-writing the markdown — every re-run drifted in tone, ordering
  and numbers. Routing through a Pydantic schema + deterministic
  template cuts variance to the LLM's intrinsic noise only.
- Templates can be swapped without touching prompts or code.
- Older clients / non-supporting models fall back to the legacy
  `generate_document(markdown=...)` path; both live side-by-side.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class ReportSection(BaseModel):
    """One chapter in the generated report.

    `body` is freeform markdown the LLM writes — that's the only
    genuinely random part. `title` is also LLM-written but the
    template enforces capitalization / numbering, so layout stays
    stable even if wording changes.
    """

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)


class ReportPayload(BaseModel):
    """Top-level structure every doc_writer bot must emit.

    The LLM is told (via system prompt) to produce this exact JSON
    shape. We then validate, retry on bad output, and render.
    """

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    sections: list[ReportSection] = Field(min_length=1, max_length=50)
    # Optional metadata for the renderer / frontend
    tags: list[str] = Field(default_factory=list, max_length=20)
    language: str = Field(default="zh", max_length=8)

    @field_validator("sections")
    @classmethod
    def _no_duplicate_titles(cls, v: list[ReportSection]) -> list[ReportSection]:
        seen: set[str] = set()
        for s in v:
            if s.title in seen:
                # Rename duplicates with a numeric suffix so the rendered
                # doc still has a unique TOC anchor.
                base = s.title
                n = 2
                while f"{base} ({n})" in seen:
                    n += 1
                s.title = f"{base} ({n})"
            seen.add(s.title)
        return v


# JSON schema description that goes into the doc_writer system prompt.
# We deliberately keep it as plain text (instead of using OpenAI's
# strict `response_format: json_schema`) so the prompt still works
# against providers that don't support strict structured output (the
# project uses a NewAPI gateway; some upstream models reject strict
# schema with 400s).
PAYLOAD_SCHEMA_DESCRIPTION: str = json.dumps(
    ReportPayload.model_json_schema(),
    ensure_ascii=False,
    indent=2,
)


def parse_payload(raw: str) -> ReportPayload:
    """Parse a raw LLM reply into a `ReportPayload`.

    Tolerates common slip-ups:
      - leading/trailing ```json fences\n      - "Here is the JSON: …" preamble\n      - JSON buried anywhere in the text (we grab the first {…} block)

    Raises `ValidationError` on schema failure.
    """
    text = (raw or "").strip()
    if not text:
        raise ValidationError.from_exception_data(
            title="ReportPayload",
            line_errors=[{"type": "missing", "msg": "empty reply"}],  # type: ignore[list-item]
            input=raw,
        )  # type: ignore[call-arg]

    # Strip markdown code fence if present.
    if text.startswith("```"):
        # find first newline, then drop everything after the closing ```
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # If there's prose before/after the JSON, try to extract the first
    # balanced top-level object.
    candidate = text
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    data: Any = json.loads(candidate)
    if not isinstance(data, dict):
        raise ValidationError.from_exception_data(
            title="ReportPayload",
            line_errors=[{"type": "type_error", "msg": "top-level must be object"}],  # type: ignore[list-item]
            input=data,
        )  # type: ignore[call-arg]
    return ReportPayload.model_validate(data)


# How the LLM is supposed to format its reply — included in the
# doc_writer manifest so older bots fall back to the legacy path
# gracefully.
PAYLOAD_INSTRUCTIONS: str = (
    "你的**整条回复**必须是一个 JSON 对象（不要包裹在 markdown 代码块里，"
    "不要任何额外文字）。结构如下：\n\n"
    "```\n" + PAYLOAD_SCHEMA_DESCRIPTION + "\n```\n\n"
    "字段说明：\n"
    "- `title`: 一句话报告主题\n"
    "- `summary`: 50–200 字执行摘要\n"
    "- `sections`: 至少 2 个章节，按报告逻辑顺序排。`title` 是章节标题，"
    "`body` 是该章节的 Markdown 正文（可空）\n"
    "- `tags`: 关键词数组，0–3 个；可选\n"
    "- `language`: `\"zh\"` / `\"en\"`\n\n"
    "**不要**返回 markdown 文本、表格、列表之外的格式；**不要**用 ``` 包裹；"
    "**不要**在 JSON 前后写解释。整条 message 只放这一个 JSON 对象。"
)