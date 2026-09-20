"use client";

import { ReactNode, useEffect, useRef, useState } from "react";
import { Avatar, avatarColor } from "./ui";
import { Bot, CitedRef } from "@/lib/api";
import { cacheAttachments, renderMessageWithMentions } from "@/lib/markdown";
import { useI18n } from "@/lib/i18n";
import { AttachmentPreviewDrawer } from "./AttachmentPreviewDrawer";
import { CitationDrawer, CitationDrawerSurface } from "./SourceCitation";
import { useCitationDrawer } from "./CitationDrawerContext";
import { CitedRefsFooter } from "./CitedRefsFooter";

/**
 * Format an ISO timestamp into a compact "HH:MM" (24-hour) string
 * for the bubble footer. We deliberately drop the date — chat
 * history is per-task and rarely spans a day, so the date adds
 * noise. Returns an empty string when the input is missing/invalid
 * so the parent can render `null` cleanly.
 */
function formatBubbleTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export type AttachmentMeta = {
  id: number;
  // Unguessable download token (see Attachment.public_id on backend).
  public_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  source: "user" | "bot";
};

export type ChatBubbleData = {
  id: string;
  role: "user" | "bot" | "system" | "error";
  botId?: number | null;
  botName?: string | null;
  content: string;
  streaming?: boolean;
  // ISO timestamp from the SSE event. Used to render a "HH:MM" line
  // under each bubble and to back the "重试" button on user prompts.
  createdAt?: string | null;
  // The original user prompt text this bubble is a reply to. Set on
  // the FIRST bot turn after a user prompt so the "重试" button can
  // re-send it without re-rendering the whole thread.
  promptSnapshot?: string | null;
  // Bot-authored attachment metadata. UI renders a download card per
  // entry. Each entry's body is served by
  // GET /api/attachments/{id}/download.
  attachments?: Array<AttachmentMeta>;
  // Stage 4: KB citations surfaced alongside this message. When the
  // markdown renderer sees a `[doc: ...]` marker it looks the key up
  // in this list and turns it into a clickable chip; the footer
  // renders one chip per unique chunk for quick scanning.
  citedRefs?: CitedRef[];
};

/**
 * Render a chat bubble. Bot bubbles use `dangerouslySetInnerHTML` because the
 * markdown output has already been sanitized (html:false) on the way in
 * and the only embedded HTML is for `<a>` / `<code>` / lists / tables / our
 * `@mention` chips. The mention chips also bind a click handler that fires
 * `mentionClick` CustomEvent so the parent composer can pre-fill the input.
 */
export function ChatBubble({
  bubble,
  bot,
  knownBots = [],
  onRetry,
}: {
  bubble: ChatBubbleData;
  bot?: Bot;
  /** All bots in the group — used to resolve @mentions inside the message. */
  knownBots?: Bot[];
  /**
   * Re-send the original user prompt. Only attached on user bubbles;
   * clicking the retry button fires `onRetry(prompt)` so the chat
   * page can pop a new SSE stream with the same text.
   */
  onRetry?: (prompt: string) => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();
  // Stage 4 fix: drawer state lives on the parent chat page, not on
  // each ChatBubble — a per-bubble `useState` would silently drop the
  // click when the user opened a chip in bubble A and then clicked a
  // chip in bubble B (B's local state was `null`). See
  // `CitationDrawerContext`.
  const { openCitation } = useCitationDrawer();

  // Wire up mention-chip clicks inside the rendered HTML.
  useEffect(() => {
    const root = bodyRef.current;
    if (!root) return;
    const handler = (e: Event) => {
      const target = (e.target as HTMLElement)?.closest(".mention");
      if (!target) return;
      const name = target.getAttribute("data-bot-name");
      if (!name) return;
      window.dispatchEvent(
        new CustomEvent("botgroup:mentionClick", {
          detail: { name, botId: target.getAttribute("data-bot-id") },
        }),
      );
    };
    root.addEventListener("click", handler);
    return () => root.removeEventListener("click", handler);
  }, [bubble.id]);

  // Citation chip clicks are handled by the delegated listener on the
  // <MessagesList> container in the chat page (it walks every bubble's
  // `citedRefs` into a single `citedByChunk` index). Wiring a second
  // per-bubble listener here would cause double-open — and historically
  // caused the "click does nothing" bug because of stale `bodyRef`
  // snapshots during the message_end → render race. See
  // `MessagesList`'s comment for the full rationale.

  if (bubble.role === "system") {
    return (
      <div
        style={{
          alignSelf: "center",
          fontSize: 11,
          color: "var(--fg-subtle)",
          padding: "4px 12px",
          background: "var(--surface-2)",
          borderRadius: 999,
          border: "1px solid var(--border)",
        }}
      >
        {bubble.content}
      </div>
    );
  }

  if (bubble.role === "error") {
    return (
      <div
        style={{
          alignSelf: "center",
          maxWidth: "70%",
          padding: "8px 14px",
          borderRadius: "var(--radius)",
          background: "var(--danger-bg)",
          border: "1px solid #FCA5A5",
          color: "#991B1B",
          fontSize: 13,
        }}
      >
        {bubble.content}
      </div>
    );
  }

  if (bubble.role === "user") {
    const ts = formatBubbleTime(bubble.createdAt);
    return (
      <div
        style={{
          alignSelf: "flex-end",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 4,
          maxWidth: "70%",
        }}
      >
        <div
          className={bubble.streaming ? "streaming" : ""}
          style={{
            padding: "10px 14px",
            borderRadius: 16,
            background:
              "linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%)",
            color: "white",
            boxShadow: "0 4px 14px rgba(167, 139, 250, 0.30)",
            fontSize: 13.5,
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {bubble.content}
        </div>
        {/* Bubble footer: time + retry. Time appears under the bubble
            (right-aligned); retry icon appears next to the time so the
            row stays compact. Hidden while streaming — the timestamp
            wouldn't have landed yet. */}
        {!bubble.streaming && (ts || onRetry) && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              paddingRight: 4,
              fontSize: 11,
              color: "var(--fg-subtle)",
            }}
          >
            {ts && <span>{ts}</span>}
            {onRetry && bubble.content && (
              <button
                type="button"
                onClick={() => onRetry(bubble.content)}
                title="重新发送这条消息"
                aria-label="重试"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 3,
                  padding: "2px 6px",
                  borderRadius: 6,
                  border: "1px solid var(--border)",
                  background: "var(--surface-2)",
                  color: "var(--fg-muted)",
                  fontSize: 11,
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--surface)";
                  e.currentTarget.style.color = "var(--accent)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "var(--surface-2)";
                  e.currentTarget.style.color = "var(--fg-muted)";
                }}
              >
                ↻ 重试
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  // Bot
  const emoji = bot?.emoji ?? "🤖";
  const name = bot?.name ?? bubble.botName ?? "Bot";
  const isSummary = !bot; // summary role uses botId = null

  // Pre-seed the markdown attachment cache so `attachment://<id>` links
  // (emitted by `generate_document`) render as proper download cards.
  const attachments = bubble.attachments;
  if (attachments && attachments.length) cacheAttachments(attachments);

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        alignSelf: "flex-start",
        maxWidth: "85%",
      }}
    >
      <Avatar emoji={emoji} size={32} color={avatarColor(name)} />
      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--fg-subtle)",
            paddingLeft: 4,
          }}
        >
          {name}
        </div>
        <div
          ref={bodyRef}
          className="chat-bubble-body"
          style={{
            padding: "10px 14px",
            borderRadius: 16,
            background: isSummary
              ? "rgba(255, 255, 255, 0.55)"
              : "rgba(255, 255, 255, 0.85)",
            border: isSummary
              ? "1px solid rgba(167, 139, 250, 0.25)"
              : "1px solid var(--border)",
            color: "var(--fg)",
            fontSize: 13.5,
            lineHeight: 1.6,
            backdropFilter: "blur(20px)",
            boxShadow: "var(--shadow-xs)",
            overflowWrap: "break-word",
            wordBreak: "break-word",
          }}
          dangerouslySetInnerHTML={{
            __html: renderMessageWithMentions(
              bubble.content,
              knownBots,
              attachments,
              bubble.citedRefs,
            ),
          }}
        />
        {!bubble.streaming && attachments && attachments.length > 0 && (
          <AttachmentCards attachments={attachments} accent={isSummary} />
        )}
        {!bubble.streaming && bubble.citedRefs && bubble.citedRefs.length > 0 && (
          <CitedRefsFooter refs={bubble.citedRefs} onOpen={openCitation} />
        )}
        {/* Bot bubble footer: timestamp only (no retry — re-sending the
            user prompt is what "重试" means, and that's already wired
            to the user bubble). */}
        {!bubble.streaming && bubble.createdAt && (
          <div
            style={{
              fontSize: 11,
              color: "var(--fg-subtle)",
              paddingLeft: 4,
            }}
          >
            {formatBubbleTime(bubble.createdAt)}
          </div>
        )}
      </div>
    </div>
  );
}

/* ──────────────────── AttachmentCards ──────────────────── */

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function attachmentEmoji(filename: string, mime: string): string {
  // Be defensive: rows from older runs may have undefined mime or
  // filename (legacy bot attachments, malformed SSE payloads, etc.).
  // Both used to crash with "Cannot read properties of undefined
  // (reading 'toLowerCase')" in the chat bubble render path.
  const ext = (filename ?? "").toLowerCase().split(".").pop() || "";
  const m = (mime ?? "").toLowerCase();
  if (["md", "markdown"].includes(ext)) return "📝";
  if (["doc", "docx"].includes(ext) || m.includes("wordprocessing")) return "📄";
  if (["xls", "xlsx", "csv"].includes(ext) || m.includes("spreadsheet")) return "📊";
  if (["ppt", "pptx"].includes(ext) || m.includes("presentation")) return "📑";
  if (["pdf"].includes(ext) || m.includes("pdf")) return "📕";
  if (["json"].includes(ext) || m.includes("json")) return "🔧";
  if (["txt", "log"].includes(ext)) return "📃";
  if (["html", "htm"].includes(ext)) return "🌐";
  if (m.startsWith("image/")) return "🖼️";
  return "📎";
}

type AttachmentCardsProps = {
  attachments: Array<AttachmentMeta>;
  accent: boolean;
};

function AttachmentCards({ attachments, accent }: AttachmentCardsProps) {
  const [previewing, setPreviewing] = useState<AttachmentMeta | null>(null);
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        marginTop: 6,
        minWidth: 260,
        maxWidth: 360,
      }}
    >
      {attachments.map((a) => {
        const isBot = a.source === "bot";
        return (
          <div
            key={a.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 12px",
              borderRadius: "var(--radius)",
              background: "var(--surface-solid)",
              border: accent
                ? "1px solid rgba(167, 139, 250, 0.35)"
                : "1px solid var(--border)",
              color: "var(--fg)",
              transition:
                "transform var(--transition), box-shadow var(--transition), border-color var(--transition)",
              boxShadow: "var(--shadow-xs)",
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget as HTMLDivElement;
              el.style.transform = "translateY(-1px)";
              el.style.boxShadow = "var(--shadow-lg)";
              el.style.borderColor = "rgba(167, 139, 250, 0.55)";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget as HTMLDivElement;
              el.style.transform = "translateY(0)";
              el.style.boxShadow = "var(--shadow-xs)";
              el.style.borderColor = accent
                ? "1px solid rgba(167, 139, 250, 0.35)"
                : "1px solid var(--border)";
            }}
          >
            <div
              style={{
                fontSize: 22,
                width: 36,
                height: 36,
                borderRadius: 10,
                background: "linear-gradient(135deg, var(--accent), var(--accent-2))",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              {attachmentEmoji(a.filename, a.mime_type)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 500,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={a.filename}
              >
                {a.filename}
              </div>
              <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2 }}>
                {formatBytes(a.size_bytes)}
                {isBot && (
                  <span style={{ marginLeft: 6, color: "var(--accent)" }}>
                    · 机器人产出
                  </span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={(ev) => {
                ev.stopPropagation();
                setPreviewing(a);
              }}
              title="预览"
              aria-label="预览"
              style={iconBtnStyle}
            >
              👁
            </button>
            <a
              href={`/api/attachments/${a.public_id}/download`}
              download
              title="下载"
              aria-label="下载"
              onClick={(ev) => ev.stopPropagation()}
              style={iconBtnStyle}
            >
              ↓
            </a>
          </div>
        );
      })}
      {previewing && (
        <AttachmentPreviewDrawer
          attachment={previewing}
          onClose={() => setPreviewing(null)}
        />
      )}
    </div>
  );
}

const iconBtnStyle: React.CSSProperties = {
  width: 30,
  height: 30,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--accent)",
  cursor: "pointer",
  fontSize: 14,
  textDecoration: "none",
  flexShrink: 0,
};