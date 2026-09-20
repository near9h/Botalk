"use client";

/**
 * Singleton markdown-it instance configured for chat-bubble rendering.
 *
 * Features enabled over defaults:
 *   - `linkify`        auto-detect plain URLs
 *   - `breaks: true`   single newline → <br> (matches typical chat style)
 *   - `html: false`    never trust raw HTML in bot output
 *
 * We also wrap the render so any `@botname` token is upgraded to a
 * highlighted, clickable chip — this is what powers bot-to-bot @mentions.
 *
 * Bot-produced document attachments use the `attachment://<id>` URL scheme,
 * which is intercepted here and turned into a real download card.
 *
 * Stage 4: RAG citation tokens `[doc: filename p.X ¶Y]` are upgraded to
 * clickable chips that the chat layer dispatches to a PDF.js viewer.
 * The chip's data-citation-chunk-id attribute is what binds the chip to
 * the persisted `cited_refs` payload — when the LLM echoes the citation
 * key inside its answer, the renderer looks the chunk_id up in
 * `cited_refsByKey` and stamps it onto the chip so the click handler can
 * fetch the bbox and open the viewer.
 */

import MarkdownIt from "markdown-it";
import type { CitedRef } from "./api";

export const md = new MarkdownIt({
  html: false,           // never render raw HTML (bot output is untrusted)
  linkify: true,         // plain URLs become clickable
  breaks: true,          // single newline → <br>
  typographer: false,     // keep punctuation literal; Chinese text reads better
});

// Cache attachment metadata so we can render filename/size on the
// download card without a second round-trip. Keyed by `public_id`
// because that's what the URL scheme uses.
type AttachmentMeta = {
  public_id: string;
  filename: string;
  size_bytes?: number;
};
const ATTACHMENT_CACHE: Map<string, AttachmentMeta> = new Map();

/** Called by the chat layer to seed the cache before rendering a message. */
export function cacheAttachments(attachments: AttachmentMeta[]): void {
  if (!Array.isArray(attachments)) return;
  for (const a of attachments) {
    if (a && typeof a.public_id === "string" && a.public_id) {
      ATTACHMENT_CACHE.set(a.public_id, a);
    }
  }
}

// `attachment://<public_id>` — public_id is a URL-safe random token
// (see Attachment.public_id on the backend), so this regex matches any
// non-empty path segment rather than restricting to digits.
const _ATTACHMENT_RE = /^attachment:\/\/([A-Za-z0-9_\-]+)$/;

function _formatBytes(n: number): string {
  if (!Number.isFinite(n)) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

// External links open in a new tab.
const DEFAULT_LINK_OPEN =
  '<a target="_blank" rel="noreferrer noopener" class="md-link">';
md.renderer.rules.link_open = function (tokens, idx, options, _env, self) {
  const token = tokens[idx];
  const href = token.attrGet("href") || "";
  const m = href.match(_ATTACHMENT_RE);
  if (m) {
    const publicId = m[1];
    const meta = ATTACHMENT_CACHE.get(publicId);
    const fname = meta?.filename || `attachment-${publicId.slice(0, 6)}`;
    const sizeText = meta?.size_bytes ? ` · ${_formatBytes(meta.size_bytes)}` : "";
    // Replace the whole <a>…</a> with a download card. The companion
    // link_close rule below just emits an empty string so the rest of the
    // markdown pipeline stays in sync.
    token.tag = "a";
    token.attrSet("href", `/api/attachments/${publicId}/download`);
    token.attrSet("download", fname);
    token.attrSet("class", "md-attachment-card");
    token.attrSet("data-attachment-id", publicId);
    // Inline label inside the link.
    return (
      '<a href="/api/attachments/' +
      publicId +
      '/download" download="' +
      escapeAttr(fname) +
      '" class="md-attachment-card" data-attachment-id="' +
      publicId +
      '" target="_self" rel="noopener">📄 ' +
      escapeAttr(fname) +
      '<span class="md-attachment-meta">' +
      escapeAttr(sizeText) +
      "</span>"
    );
  }
  const targetIdx = token.attrIndex("target");
  if (targetIdx < 0) {
    token.attrPush(["target", "_blank"]);
  } else {
    token.attrs![targetIdx][1] = "_blank";
  }
  const relIdx = token.attrIndex("rel");
  if (relIdx < 0) {
    token.attrPush(["rel", "noreferrer noopener"]);
  } else {
    token.attrs![relIdx][1] = "noreferrer noopener";
  }
  // Always include our custom class for styling.
  const classIdx = token.attrIndex("class");
  if (classIdx < 0) {
    token.attrPush(["class", "md-link"]);
  } else {
    token.attrs![classIdx][1] = "md-link";
  }
  return self.renderToken(tokens, idx, options);
};

// link_close after an attachment card is empty (the link_open already
// emitted the full card markup).
md.renderer.rules.link_close = function (tokens, idx, options, _env, self) {
  // Find the matching link_open to detect the attachment scheme.
  for (let i = idx - 1; i >= 0; i--) {
    const t = tokens[i];
    if (t.type !== "link_open") continue;
    const href = t.attrGet("href") || "";
    if (_ATTACHMENT_RE.test(href)) {
      return "</a>";
    }
    break;
  }
  return self.renderToken(tokens, idx, options);
};

// Add `target` + `rel` to any autolinked plain-URL links too.
// (linkify runs before the renderer; the resulting tokens have href but no target.)
md.renderer.rules.autolink_open = function (tokens, idx, options, _env, self) {
  const token = tokens[idx];
  token.attrSet("target", "_blank");
  token.attrSet("rel", "noreferrer noopener");
  token.attrSet("class", "md-link");
  return self.renderToken(tokens, idx, options);
};

// Render ` ```echarts-html ` fenced blocks (emitted by the chart tool) as a
// sandboxed iframe instead of an escaped <pre>. `html:false` means the raw
// chart document is normally shown as text; the fence renderer returns real
// HTML so the ECharts document actually runs, but inside `sandbox` so it
// can't touch the host page. `escapeAttr` is declared below and hoisted.
const defaultFence = md.renderer.rules.fence;

md.renderer.rules.fence = function (tokens, idx, options, env, self) {
  const token = tokens[idx];
  if ((token.info || "").trim() === "echarts-html") {
    const srcdoc = escapeAttr(token.content);
    return (
      '<div class="chart-frame">' +
      '<iframe sandbox="allow-scripts" loading="lazy" title="chart" ' +
      'style="width:100%;height:420px;border:0;border-radius:12px;background:#fff;" ' +
      'srcdoc="' + srcdoc + '"></iframe>' +
      "</div>"
    );
  }
  if (defaultFence) return defaultFence(tokens, idx, options, env, self);
  return self.renderToken(tokens, idx, options);
};

/**
 * Pre-process: convert `@botname` tokens (CJK-aware) into a placeholder
 * `<span class="mention" data-bot="botname">@botname</span>` so the
 * renderer doesn't escape them. We do this *before* markdown rendering so
 * we preserve the full token through tables / lists / headings.
 */

import { Bot } from "./api";

// Match `@SomeBot` / `@中文名` / `@数字` (no whitespace).
// Limit to ~24 chars to avoid grabbing huge strings; reject if followed
// by another CJK char (so `@张三` is fine but `@张三李四王五` would match
// up to the boundary at the first delimiter char).
const MENTION_PATTERN = /@([一-鿿\w][一-鿿\w·\-\d]{0,23})/g;

// Match RAG citation tokens. We accept two shapes the LLM may emit:
//   `[doc: filename p.X ¶Y]` — the canonical filename-form marker
//   `[1]`, `[2]`, …                       — short numbered reference
// The chat prompt now lists chunks under numbered labels (`[1]`,
// `[2]`, …) so most LLMs prefer the short form. We resolve both to the
// same chunk via a single Map keyed by `citation_key` (for the long
// form) and a separate ordinal→chunk map (for the short form).
const CITATION_PATTERN = /\[doc:\s([^\]]+)\]/g;
// `[N]` references: 1-3 digit number. We deliberately *don't* match
// `[2025]` (year-style) — the rule requires a tight boundary. The
// `\s*` allows LLM-emitting formats like `[1 ]` / `[1] `.
const CITATION_SHORT_PATTERN = /\[(\d{1,3})\]/g;

// Index `cited_refs` by their pre-formatted `citation_key` so we can
// resolve `[doc: ...]` markers back to chunk_ids without re-parsing the
// filename. The backend writes the same key the LLM is told to echo, so
// this is a stable lookup.
function buildCitationIndex(refs: CitedRef[] | undefined): Map<string, CitedRef> {
  const idx = new Map<string, CitedRef>();
  if (!refs) return idx;
  for (const r of refs) {
    if (r && typeof r.citation_key === "string") idx.set(r.citation_key, r);
  }
  return idx;
}

// 长形式 `[doc: <key>]` 与短编号 `[N]` 的合并扫描正则：一次遍历按
// 出现顺序处理两种标记，得到的编号与渲染出来的角标数字一致。
const CITATION_ANY_PATTERN = /\[doc:\s([^\]]+)\]|\[(\d{1,3})\]/g;

/**
 * 返回一条消息正文里**真正被引用**的 chunk（按角标编号升序）。
 *
 * `cited_refs` 的语义是「本次检索命中并注入提示词的候选 chunk」，不等
 * 于「回答引用到的来源」——提示词把它们编号列给 LLM，LLM 只给自己用到
 * 的那些标 `[N]`。所以底部来源条不能直接全量渲染 `cited_refs`，否则会
 * 出现「正文 4 个角标、底下 5 条来源」。
 *
 * `ordinal` 直接取角标上的数字：短编号形式就是 LLM 写的 n（因为 n 就是
 * `cited_refs` 里的序号，与提示词给出的编号一致），`[doc: …]` 形式沿用
 * 渲染器的递增序号。这样底部括号里的数字与正文角标严格一致。
 */
export function resolveCitedChunks(
  text: string,
  citedRefs: CitedRef[] | undefined,
): Array<{ ref: CitedRef; ordinal: number }> {
  const out: Array<{ ref: CitedRef; ordinal: number }> = [];
  if (!text || !citedRefs || citedRefs.length === 0) return out;

  const citationIndex = buildCitationIndex(citedRefs);
  const citationIndexNoSpace = new Map<string, CitedRef>();
  for (const [k, v] of citationIndex.entries()) {
    citationIndexNoSpace.set(k.replace(/\s+/g, ""), v);
  }
  // 短编号 `[N]` 的 N 是 `cited_refs` 里的第 N 条（跳过 chunk_id 非数字
  // 的脏数据）——与渲染器 `chunksByOrdinal` 的取法完全一致。
  const chunksByOrdinal: CitedRef[] = [];
  for (const r of citedRefs) {
    if (r && typeof r.chunk_id === "number") chunksByOrdinal.push(r);
  }

  const seen = new Set<number>();
  const longOrdinalByChunk = new Map<number, number>();
  let longOrdinal = 0;

  CITATION_ANY_PATTERN.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = CITATION_ANY_PATTERN.exec(text)) !== null) {
    let ref: CitedRef | undefined;
    let ordinal: number;
    if (m[1] !== undefined) {
      const key = m[1].trim();
      ref =
        citationIndex.get(key) ??
        citationIndexNoSpace.get(key.replace(/\s+/g, ""));
      if (!ref) continue;
      let n = longOrdinalByChunk.get(ref.chunk_id);
      if (n == null) {
        longOrdinal += 1;
        n = longOrdinal;
        longOrdinalByChunk.set(ref.chunk_id, n);
      }
      ordinal = n;
    } else {
      const n = Number(m[2]);
      // 越界的 `[N]` 渲染器会原样留成普通文本（不是引用），这里同样跳过。
      if (!Number.isFinite(n) || n < 1 || n > chunksByOrdinal.length) continue;
      ref = chunksByOrdinal[n - 1];
      ordinal = n;
    }
    if (!ref || seen.has(ref.chunk_id)) continue;
    seen.add(ref.chunk_id);
    out.push({ ref, ordinal });
  }
  out.sort((a, b) => a.ordinal - b.ordinal);
  return out;
}

export function renderMessageWithMentions(
  text: string,
  knownBots: Bot[],
  attachments?: AttachmentMeta[],
  cited_refs?: CitedRef[],
): string {
  // Seed attachment cache so link_open can render filename / size on the
  // download card without a separate fetch.
  if (attachments && attachments.length) cacheAttachments(attachments);

  // 1. Find all @ mentions, lowercased for matching.
  // 2. If a bot with a same name (case-insensitive) exists, wrap as chip.
  // 3. Otherwise keep the literal `@name` text and let markdown render it.
  const knownNames = new Map<string, Bot>();
  for (const b of knownBots) {
    if (!b.name) continue;
    knownNames.set(b.name.toLowerCase(), b);
  }

  // Citation lookup table — see CITATION_PATTERN above.
  const citationIndex = buildCitationIndex(cited_refs);
  // LLM-echoed citation keys sometimes drift from the prompt's exact
  // formatting (extra spaces, full-width vs half-width `¶`, etc.). Build
  // a whitespace-stripped secondary index so `[doc: foo.pdf p.3 ¶1]`
  // still resolves when the LLM emits `[doc: foo.pdf  p.3 ¶ 1 ]`.
  const citationIndexNoSpace = new Map<string, CitedRef>();
  for (const [k, v] of citationIndex.entries()) {
    citationIndexNoSpace.set(k.replace(/\s+/g, ""), v);
  }
  // Numbered ordinal → chunk. We assign in the order chunks appear in
  // `cited_refs`, which matches the numbering the prompt template
  // emits (`[1]`, `[2]`, …). If `cited_refs` is empty the map is also
  // empty and `[N]` markers fall through to the orphan branch.
  const chunksByOrdinal: CitedRef[] = [];
  for (const r of cited_refs ?? []) {
    if (r && typeof r.chunk_id === "number") chunksByOrdinal.push(r);
  }

  // Strip a leading `[name] ` speaker prefix (added by the orchestrator
  // so other bots can tell voices apart in their prompt). Only at the
  // very start of the message and only when it matches a known bot —
  // anything else is left alone so users can still write `[literal]`.
  // We do this BEFORE markdown rendering so a reply like
  //   "[部门长] ## 最终定调\n\n正文..."
  // becomes
  //   "## 最终定调\n\n正文..."
  // and markdown parses the heading instead of treating `##` as literal.
  const LEADING_PREFIX = /^\s*\[([^\]\n]{1,32})\]\s*/;
  const m = text.match(LEADING_PREFIX);
  if (m && knownNames.has(m[1].toLowerCase())) {
    text = text.slice(m[0].length);
  }

  // We replace mentions inside the raw text BEFORE rendering. markdown-it
  // will then pass the embedded `<span class="mention">` through verbatim
  // because `html: false` only blocks raw HTML at the markdown source
  // level — once we hand the string to its render, `html: false` means
  // the HTML we inserted at *preprocessing* time survives intact only if
  // we tell markdown-it to allow specific tags. The simplest reliable
  // path is to use a placeholder string and substitute after render.
  const placeholders: string[] = [];
  const withPlaceholders = text.replace(MENTION_PATTERN, (full, raw) => {
    const key = String(raw).toLowerCase();
    const bot = knownNames.get(key);
    if (!bot) return full; // leave as-is
    const idx = placeholders.length;
    placeholders.push(
      `<span class="mention" data-bot-id="${bot.id}" data-bot-name="${escapeAttr(bot.name)}" data-bot-emoji="${escapeAttr(bot.emoji)}">@${escapeAttr(bot.name)}</span>`,
    );
    return `@@MENTION_${idx}@@`;
  });

  // Replace `[doc: key]` markers with citation chips. The chip is now a
  // compact superscript index `[1]`, `[2]`... assigned in the order the
  // refs first appear in the text. This keeps the inline answer tidy
  // (no more long `📎 filename p.X ¶Y` strings) while preserving the
  // exact same data attributes the chat-page click handler already
  // dispatches on (`data-citation-chunk-id`, `data-citation-kb-id`, …)
  // so the right-side drawer still opens the matching chunk.
  //
  // When the citation key isn't in `citationIndex` (i.e. the LLM
  // echoed something we can't resolve) we emit a small `?` superscript
  // instead of a long string — the user sees something obviously
  // missing, but the bubble body stays compact.
  let citeOrdinal = 0;
  const ordinalByKey = new Map<number, number>();
  const withCitations = withPlaceholders.replace(CITATION_PATTERN, (full, rawKey) => {
    const key = String(rawKey).trim();
    // Primary: exact key match. Fallback: strip all whitespace so the
    // LLM's reformatting (extra spaces, line wraps in code blocks, etc.)
    // doesn't drop the citation to the non-clickable `?` orphan branch.
    const ref = citationIndex.get(key) ?? citationIndexNoSpace.get(key.replace(/\s+/g, ""));
    const idx = placeholders.length;
    if (ref) {
      // Stable ordinal per unique chunk: same chunk_id in the same
      // bubble always shows the same number, even if cited twice.
      let n = ordinalByKey.get(ref.chunk_id);
      if (n == null) {
        citeOrdinal += 1;
        n = citeOrdinal;
        ordinalByKey.set(ref.chunk_id, n);
      }
      placeholders.push(
        `<sup class="citation" data-citation-chunk-id="${ref.chunk_id}" data-citation-key="${escapeAttr(key)}" data-citation-kb-id="${ref.kb_id}" data-citation-doc-id="${ref.kb_doc_id}" title="${escapeAttr(ref.snippet || key)}">[${n}]</sup>`,
      );
    } else {
      placeholders.push(
        `<sup class="citation citation--orphan" data-citation-key="${escapeAttr(key)}" title="${escapeAttr(key)}">?</sup>`,
      );
    }
    return `@@MENTION_${idx}@@`;
  });

  // Render the rest of the markdown. The placeholders are escaped because
  // they look like text, so they end up rendered as plain text — we'll
  // substitute them back as raw HTML *after* parsing.
  let html = md.render(withCitations);

  // Substitute `[doc: …]` placeholders back as raw HTML.
  html = html.replace(/@@MENTION_(\d+)@@/g, (_match, n) => {
    const idx = Number(n);
    return placeholders[idx] ?? "";
  });

  // Second pass: handle the short `[N]` numbered form. The current
  // prompt encourages the LLM to write `[1] [2] …` after each cited
  // fact. These tokens survive markdown rendering as text (markdig's
  // linkify would otherwise turn `[1]` into a reference link, but
  // without a matching reference definition it stays as plain text —
  // which is what we want). We do a fresh placeholder round so we can
  // keep the markdig-unsafe `<sup>` injection off the markdown pipeline.
  if (chunksByOrdinal.length > 0) {
    const shortPlaceholders: string[] = [];
    html = html.replace(CITATION_SHORT_PATTERN, (full, rawN) => {
      const n = Number(rawN);
      if (!Number.isFinite(n) || n < 1 || n > chunksByOrdinal.length) {
        return full; // leave non-citation `[12]` alone
      }
      const ref = chunksByOrdinal[n - 1];
      const idx = shortPlaceholders.length;
      shortPlaceholders.push(
        `<sup class="citation" data-citation-chunk-id="${ref.chunk_id}" data-citation-kb-id="${ref.kb_id}" data-citation-doc-id="${ref.kb_doc_id}" data-citation-key="${escapeAttr(ref.citation_key)}" title="${escapeAttr(ref.snippet || ref.citation_key)}">[${n}]</sup>`,
      );
      return `@@SHORT_${idx}@@`;
    });
    html = html.replace(/@@SHORT_(\d+)@@/g, (_m, i) => {
      const idx = Number(i);
      return shortPlaceholders[idx] ?? "";
    });
  }

  return html;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}