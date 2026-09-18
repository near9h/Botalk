"use client";

import { ReactNode, useEffect, useRef, useState } from "react";
import { Avatar, avatarColor } from "./ui";
import { Bot } from "@/lib/api";
import { cacheAttachments, renderMessageWithMentions } from "@/lib/markdown";
import { useI18n } from "@/lib/i18n";
import { AttachmentPreviewDrawer } from "./AttachmentPreviewDrawer";

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
  // Bot-authored attachment metadata. UI renders a download card per
  // entry. Each entry's body is served by
  // GET /api/attachments/{id}/download.
  attachments?: Array<AttachmentMeta>;
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
}: {
  bubble: ChatBubbleData;
  bot?: Bot;
  /** All bots in the group — used to resolve @mentions inside the message. */
  knownBots?: Bot[];
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();

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
    return (
      <div
        className={bubble.streaming ? "streaming" : ""}
        style={{
          alignSelf: "flex-end",
          maxWidth: "70%",
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
            __html: renderMessageWithMentions(bubble.content, knownBots, attachments),
          }}
        />
        {!bubble.streaming && attachments && attachments.length > 0 && (
          <AttachmentCards attachments={attachments} accent={isSummary} />
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
  const ext = filename.toLowerCase().split(".").pop() || "";
  const m = mime.toLowerCase();
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