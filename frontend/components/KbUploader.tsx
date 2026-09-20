"use client";

/**
 * Stage 2 + Stage 5: drag-drop + click-to-upload for one KB.
 *
 * Mirrors the chat-attachment upload pipeline but only the surface area
 * the user sees: a single "选择文件 / 拖拽到此处" button + the row of
 * newly-uploaded docs with their ingest status. The KB-detail page
 * owns the polling loop that refreshes each doc's status; this component
 * is presentational + emits `onUploaded(doc)` so the parent can splice
 * the new row into its document list.
 *
 * We deliberately keep this dumb about KB state: the parent page is
 * responsible for refetching the doc list / showing the success toast.
 */
import { useRef, useState } from "react";
import { api, KbDocument } from "@/lib/api";
import { useToast } from "@/components/ui";
import { useI18n } from "@/lib/i18n";

export function KbUploader({
  kbId,
  onUploaded,
}: {
  kbId: string;
  onUploaded?: (doc: KbDocument) => void;
}) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        try {
          const doc = await api.uploadKbDocument(kbId, f);
          toast.push({
            title: t("kbUploader.toast.okFmt", { name: f.name }),
            description: t("kbUploader.toast.okDesc"),
            variant: "success",
          });
          onUploaded?.(doc);
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          toast.push({
            title: t("kbUploader.toast.failFmt", { name: f.name }),
            description: msg,
            variant: "error",
          });
        }
      }
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        void upload(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
      style={{
        padding: 18,
        borderRadius: "var(--radius)",
        border: dragOver
          ? "2px dashed var(--accent)"
          : "2px dashed var(--border)",
        background: dragOver
          ? "rgba(167, 139, 250, 0.06)"
          : "var(--surface-2)",
        cursor: busy ? "wait" : "pointer",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 6,
        transition: "all var(--transition)",
      }}
    >
      <div style={{ fontSize: 24 }}>{busy ? "⏳" : "📤"}</div>
      <div style={{ fontSize: 13, fontWeight: 500 }}>
        {busy ? t("kbUploader.uploading") : t("kbUploader.prompt")}
      </div>
      <div style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
        {t("kbUploader.hint")}
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.markdown,.html,.htm,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/plain,text/markdown,text/html"
        style={{ display: "none" }}
        onChange={(e) => void upload(e.target.files)}
      />
    </div>
  );
}