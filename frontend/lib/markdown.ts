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
 */

import MarkdownIt from "markdown-it";

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

export function renderMessageWithMentions(
  text: string,
  knownBots: Bot[],
  attachments?: AttachmentMeta[],
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

  // Render the rest of the markdown. The placeholders are escaped because
  // they look like text, so they end up rendered as plain text — we'll
  // substitute them back as raw HTML *after* parsing.
  let html = md.render(withPlaceholders);

  // Substitute placeholders back. markdown-it escaped `@@MENTION_N@@` to
  // text content; we need to put raw HTML back in. We do a literal string
  // replace (the placeholder sequence is unique per render).
  html = html.replace(/@@MENTION_(\d+)@@/g, (_match, n) => {
    const idx = Number(n);
    return placeholders[idx] ?? "";
  });

  return html;
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}