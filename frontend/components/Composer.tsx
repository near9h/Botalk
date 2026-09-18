"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "./ui";
import { api, Attachment, Bot } from "@/lib/api";

export function Composer({
  bots,
  onSend,
  onStop,
  streaming,
  groupId,
}: {
  bots: Bot[];
  onSend: (prompt: string, attachments: Attachment[]) => void;
  onStop?: () => void;
  streaming: boolean;
  groupId?: string;
}) {
  const [value, setValue] = useState("");
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const ref = useRef<HTMLTextAreaElement>(null);

  // Listen for clicks on @mention chips rendered inside chat bubbles. The
  // chip click dispatches a `botgroup:mentionClick` CustomEvent with the
  // bot name; we append "@Name " to the current input.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ name: string; botId: string | null }>).detail;
      if (!detail?.name) return;
      const mention = `@${detail.name} `;
      setValue((prev) => {
        // Don't double-insert the same trailing mention.
        if (prev.endsWith(mention) || prev.endsWith(`@${detail.name} `)) return prev;
        return prev ? prev + (prev.endsWith(" ") ? "" : " ") + mention : mention;
      });
      setMentionOpen(false);
      setTimeout(() => ref.current?.focus(), 0);
    };
    window.addEventListener("botgroup:mentionClick", handler);
    return () => window.removeEventListener("botgroup:mentionClick", handler);
  }, []);

  // Auto-grow textarea
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [value]);

  const send = () => {
    const v = value.trim();
    if ((!v && attachments.length === 0) || streaming) return;
    onSend(v, attachments);
    setValue("");
    setMentionOpen(false);
    setMentionQuery("");
    setAttachments([]);
    setUploadError(null);
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    for (const file of Array.from(files)) {
      const slotId = Date.now() + Math.random();
      setUploading(slotId);
      try {
        const att = await api.uploadAttachment(file, groupId);
        setAttachments((prev) => [...prev, att]);
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : String(e));
      } finally {
        setUploading(null);
      }
    }
    // Allow re-selecting the same file
    if (fileRef.current) fileRef.current.value = "";
  };

  const removeAttachment = (id: number) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value;
    setValue(v);
    // Detect @ mention in progress
    const cursor = e.target.selectionStart;
    const upToCursor = v.slice(0, cursor ?? v.length);
    const atIdx = upToCursor.lastIndexOf("@");
    if (atIdx === -1) {
      setMentionOpen(false);
      return;
    }
    const chunk = upToCursor.slice(atIdx + 1);
    if (/\s/.test(chunk)) {
      setMentionOpen(false);
      return;
    }
    setMentionQuery(chunk);
    setMentionOpen(true);
  };

  const insertMention = (b: Bot) => {
    const cursor = ref.current?.selectionStart ?? value.length;
    const atIdx = value.lastIndexOf("@", cursor - 1);
    const before = value.slice(0, atIdx);
    const after = value.slice(cursor);
    const inserted = `@${b.name} `;
    setValue(before + inserted + after);
    setMentionOpen(false);
    setMentionQuery("");
    setTimeout(() => ref.current?.focus(), 0);
  };

  const filtered = bots.filter((b) =>
    b.name.toLowerCase().includes(mentionQuery.toLowerCase()),
  );

  return (
    <div
      className="glass-strong"
      style={{
        position: "relative",
        padding: 8,
        display: "flex",
        gap: 8,
        alignItems: "flex-end",
      }}
    >
      {/* Attachment + textarea column */}
      <div style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column", gap: 6 }}>
        {/* Attachment chips */}
        {attachments.length > 0 && (
          <div
            style={{
              display: "flex",
              gap: 6,
              flexWrap: "wrap",
              padding: "0 4px",
            }}
          >
            {attachments.map((a) => (
              <span
                key={a.id}
                className="glass"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "4px 8px",
                  borderRadius: 999,
                  fontSize: 11,
                  color: "var(--fg-muted)",
                }}
                title={`${a.filename} · ${(a.size_bytes / 1024).toFixed(0)} KB`}
              >
                📎 <span style={{ fontWeight: 500 }}>{a.filename}</span>
                <span style={{ color: "var(--fg-subtle)" }}>
                  {a.content_chars != null ? `${a.content_chars} 字` : ""}
                </span>
                <button
                  type="button"
                  onClick={() => removeAttachment(a.id)}
                  aria-label="移除附件"
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: 999,
                    background: "transparent",
                    border: "none",
                    color: "var(--fg-subtle)",
                    cursor: "pointer",
                  }}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {uploadError && (
          <div
            style={{
              fontSize: 11,
              color: "var(--danger)",
              padding: "0 4px",
            }}
          >
            上传失败:{uploadError}
          </div>
        )}

      <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 6 }}>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg,.webp,.gif,.bmp,.jp2,.htm,.html"
          style={{ display: "none" }}
          onChange={(e) => handleFiles(e.target.files)}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={uploading !== null || streaming}
          title="上传附件(PDF/DOC/图片,自动用 MinerU 转 Markdown 加入对话)"
          aria-label="上传附件"
          style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: uploading !== null ? "var(--surface-2)" : "transparent",
            color: "var(--fg-muted)",
            fontSize: 16,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: uploading !== null ? "wait" : "pointer",
            flexShrink: 0,
          }}
        >
          {uploading !== null ? "⏳" : "📎"}
        </button>
        <div style={{ flex: 1, position: "relative" }}>
        <textarea
          ref={ref}
          value={value}
          onChange={handleChange}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !mentionOpen) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="输入消息… 使用 @机器人名 触发指定机器人  (Enter 发送 / Shift+Enter 换行)"
          rows={1}
          style={{
            width: "100%",
            border: "none",
            background: "transparent",
            resize: "none",
            padding: "8px 12px",
            fontSize: 14,
            lineHeight: 1.55,
            outline: "none",
            color: "var(--fg)",
            fontFamily: "inherit",
          }}
        />
        {mentionOpen && filtered.length > 0 && (
          <div
            className="glass-strong animate-scale-in"
            style={{
              position: "absolute",
              bottom: "calc(100% + 8px)",
              left: 0,
              minWidth: 240,
              maxHeight: 240,
              overflow: "auto",
              padding: 6,
              zIndex: 20,
            }}
          >
            {filtered.map((b) => (
              <button
                key={b.id}
                onClick={() => insertMention(b)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 10px",
                  borderRadius: "var(--radius-sm)",
                  width: "100%",
                  textAlign: "left",
                  transition: "background var(--transition)",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLButtonElement).style.background =
                    "rgba(15, 23, 42, 0.05)")
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLButtonElement).style.background = "transparent")
                }
              >
                <span style={{ fontSize: 18 }}>{b.emoji}</span>
                <span style={{ fontWeight: 500, fontSize: 13 }}>{b.name}</span>
                <span
                  style={{
                    marginLeft: "auto",
                    fontSize: 11,
                    color: "var(--fg-subtle)",
                    fontFamily: '"JetBrains Mono", monospace',
                  }}
                >
                  {b.model}
                </span>
              </button>
            ))}
          </div>
        )}
        </div>
        </div>
      </div>
      {streaming ? (
        <Button variant="danger" onClick={onStop} size="md">
          ⏹ 停止
        </Button>
      ) : (
        <Button
          onClick={send}
          disabled={!value.trim() && attachments.length === 0}
          size="md"
        >
          发送 <span style={{ marginLeft: 4, opacity: 0.7, fontSize: 11 }}>⏎</span>
        </Button>
      )}
    </div>
  );
}