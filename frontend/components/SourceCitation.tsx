"use client";

/**
 * Stage 4: Citation chip UI + preview modal for the PDF.js viewer.
 *
 * Two pieces:
 *   - <CitationChip citedRef={…} onOpen={…} /> renders a single
 *     clickable chip used both inline (in the bot answer, via the
 *     markdown pipeline) and as the footer entry in <CitedRefsFooter />.
 *   - <CitationPreviewModal citedRef={…} onClose={…} /> opens the
 *     PdfViewerWithBbox in a centered popup so the user gets the
 *     highlighted page without leaving the conversation.
 *
 * The chip is the only "always-visible" surface — clicking it opens the
 * preview modal for that citation (bbox comes straight off the `CitedRef`
 * carried through SSE, no extra fetch needed).
 *
 * IMPORTANT — why the prop is named `citedRef` and NOT `ref`:
 * `ref` is a reserved prop in React. `createElement` / the jsx runtime
 * lifts `ref` out of props before the component ever sees them, so a
 * plain function component that destructures `{ ref }` from its props
 * always gets `undefined`. The previous revision used
 * `<CitationDrawer ref={openRef} … />`, which made the drawer bail out
 * on its `if (!ref) return null` guard every single time — clicking a
 * citation updated the context state but rendered nothing (and, because
 * React only warns about this in dev builds, it failed silently in
 * production). Keep the name `citedRef`.
 */
import { useEffect, useState } from "react";
import type { CitedRef } from "@/lib/api";
import { isPreviewableSource, kbDocumentPreviewUrl } from "@/lib/api";
import { PdfViewerWithBbox, type PdfHighlight } from "./PdfViewerWithBbox";
import { useI18n } from "@/lib/i18n";

export type CitationChipProps = {
  // Accept `CitedRef | undefined` so callers iterating `refs` don't
  // have to filter out null entries — we render a disabled stub chip
  // for those instead of throwing at render time. The marshalling
  // path (orchestrator → SSE → frontend) occasionally emits a
  // null entry when a chunk lookup happens before the assistant JSON
  // is fully parsed; rendering must remain robust.
  citedRef: CitedRef | null | undefined;
  onOpen: (citedRef: CitedRef) => void;
};

/**
 * Single clickable chip. Compact, fits both inline (in chat) and as
 * a footer entry. Color = accent (purple) so the user can distinguish
 * a citation from a plain mention or attachment.
 */
export function CitationChip({ citedRef, onOpen }: CitationChipProps) {
  const { t } = useI18n();
  const label = shortLabel(citedRef, t("citation.unknownSource"));
  const title = citedRef?.snippet || citedRef?.citation_key || label;
  // Nullish ref → render a non-interactive "未知来源" pill. We don't
  // want to throw `Cannot read properties of undefined` here because
  // the chat page is already scrolled past the bubble.
  if (!citedRef) {
    return (
      <span
        aria-disabled="true"
        title={label}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          margin: "0 2px",
          fontSize: 11.5,
          borderRadius: 999,
          background: "rgba(148, 163, 184, 0.18)",
          color: "var(--fg-muted)",
          border: "1px solid rgba(148, 163, 184, 0.45)",
          whiteSpace: "nowrap",
        }}
      >📎 {label}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onOpen(citedRef);
      }}
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        margin: "0 2px",
        fontSize: 11.5,
        fontWeight: 500,
        borderRadius: 999,
        background: "rgba(167, 139, 250, 0.14)",
        color: "var(--accent)",
        border: "1px solid rgba(167, 139, 250, 0.35)",
        cursor: "pointer",
        transition: "all var(--transition)",
        whiteSpace: "nowrap",
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget;
        el.style.background = "rgba(167, 139, 250, 0.22)";
        el.style.borderColor = "rgba(167, 139, 250, 0.55)";
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget;
        el.style.background = "rgba(167, 139, 250, 0.14)";
        el.style.borderColor = "rgba(167, 139, 250, 0.35)";
      }}
    >
      📎 {label}
    </button>
  );
}

/**
 * Centered popup that hosts the PDF.js viewer for one citation.
 *
 * The bytes come from the backend's unified
 * `GET /api/kb/{kb_id}/documents/{doc_id}/preview`: a PDF source is served
 * as-is, a Word / PPT / Excel source is converted to PDF server-side
 * (LibreOffice, cached on disk). So no per-format branching is needed
 * here — we only check whether the extension is one the backend can
 * render, and otherwise show the chip metadata (snippet + page) without a
 * live PDF.
 */
export function CitationPreviewModal({
  citedRef,
  onClose,
}: {
  citedRef: CitedRef | null;
  onClose: () => void;
}) {
  const [pdfSrc, setPdfSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

  // Esc closes it. Only bind while open so other Esc handlers (modal
  // dialogs elsewhere on the page) keep working when the modal is
  // closed.
  useEffect(() => {
    if (!citedRef) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [citedRef, onClose]);

  useEffect(() => {
    if (!citedRef) {
      setPdfSrc(null);
      setError(null);
      return;
    }
    // 预览统一走后端的 /preview：PDF 直接回原文件，Word / PPT / Excel
    // 由服务端用 LibreOffice 转成 PDF（结果落盘缓存）。所以这里不再需要
    // 先查 doc 拿 public_id、也不用判断 mime。
    if (!isPreviewableSource(citedRef.filename)) {
      setPdfSrc(null);
      setError(
        t("citation.unsupportedFmt", { filename: citedRef.filename }),
      );
      return;
    }
    setError(null);
    setPdfSrc(kbDocumentPreviewUrl(citedRef.kb_id, citedRef.kb_doc_id));
  }, [citedRef]);

  if (!citedRef) return null;

  const highlights: PdfHighlight[] = citedRef.bbox
    ? [{ page: citedRef.page || 1, bbox: citedRef.bbox, label: citedRef.citation_key }]
    : citedRef.page
      ? [{ page: citedRef.page, bbox: null, label: citedRef.citation_key }]
      : [];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${t("citation.preview", { filename: citedRef.filename || "" })}`}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "rgba(15, 23, 42, 0.45)",
        backdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      {/* Centered popup: keeps the original PDF-viewer-first layout. The
          chunk snippet is exposed via a separate, smaller popover
          (CitationSnippetPopover) — see the chat page. The user wanted
          snippet *out* of this drawer so the PDF stays full-width. */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="glass-strong animate-scale-in"
        style={{
          width: "min(900px, 100%)",
          maxHeight: "calc(100vh - 48px)",
          overflowY: "auto",
          background: "var(--surface-solid)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          boxShadow: "var(--shadow-lg)",
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, wordBreak: "break-word" }}>
              {t("citation.preview", { filename: citedRef.filename })}
            </div>
            <div
              style={{
                fontSize: 12,
                color: "var(--fg-subtle)",
                marginTop: 2,
              }}
            >
              {citedRef.page ? t("citation.pageFmt", { n: citedRef.page }) : t("citation.allPages")}
              {citedRef.para != null ? t("citation.paraFmt", { n: citedRef.para }) : ""}
              {citedRef.score ? t("citation.scoreFmt", { p: (citedRef.score * 100).toFixed(1) }) : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("citation.closeAria")}
            style={{
              border: "1px solid var(--border)",
              background: "var(--surface-2)",
              borderRadius: 8,
              width: 32,
              height: 32,
              cursor: "pointer",
              fontSize: 14,
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>

        {error && (
          <div
            style={{
              padding: 12,
              borderRadius: 8,
              background: "var(--danger-bg)",
              color: "#991B1B",
              fontSize: 13,
            }}
          >
            {error}
          </div>
        )}

        {citedRef.snippet && (
          <details
            style={{
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "var(--surface-2)",
              padding: "6px 12px",
            }}
          >
            <summary
              style={{
                cursor: "pointer",
                fontSize: 11,
                fontWeight: 700,
                color: "var(--fg-subtle)",
                letterSpacing: 0.5,
                textTransform: "uppercase",
                userSelect: "none",
                listStyle: "none",
              }}
            >
              {t("citation.snippetTitle")}
            </summary>
            <div
              style={{
                marginTop: 8,
                fontSize: 13,
                lineHeight: 1.7,
                color: "var(--fg)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxHeight: 200,
                overflowY: "auto",
              }}
            >
              {citedRef.snippet}
              <div
                style={{
                  marginTop: 8,
                  paddingTop: 6,
                  borderTop: "1px dashed var(--border)",
                  fontSize: 10,
                  color: "var(--fg-subtle)",
                  lineHeight: 1.4,
                }}
              >
                {t("citation.snippetNote")}
              </div>
            </div>
          </details>
        )}

        {pdfSrc && (
          <PdfViewerWithBbox
            src={pdfSrc}
            highlights={highlights}
            title={t("citation.viewerTitle")}
            width={840}
          />
        )}
      </div>
    </div>
  );
}

/**
 * Compact standalone popover that shows the chunk snippet the LLM was
 * given for a citation. Currently unused — the snippet is shown inside
 * the PDF drawer's <details> block, which is the user-facing
 * delivery. Kept here as a stable export so other surfaces (e.g. an
 * admin / debug view) can mount the popover without re-importing
 * internals.
 */
export function CitationSnippetPopover(_props: {
  citedRef: CitedRef;
  anchorRect: { top: number; left: number; bottom: number; right: number } | null;
  onClose: () => void;
}) {
  return null;
}

/** Compact chip label: drop the .pdf extension, keep `p.X ¶Y`.
 *
 * Defensive against malformed payloads: when `cited_refs` arrives with
 * a nullish entry (e.g. a streaming `message_end` whose chunk lookup
 * happened before the assistant JSON was fully parsed), we'd
 * otherwise throw `Cannot read properties of undefined (reading
 * 'citation_key')` at render time. Fall through to the filename or
 * a generic placeholder so the bubble still renders.
 */
function shortLabel(citedRef: CitedRef | undefined | null, unknownLabel: string): string {
  if (!citedRef) return unknownLabel;
  // citation_key looks like `<filename> p.X ¶Y`. We strip the extension
  // off the filename so the chip stays compact.
  const key = citedRef.citation_key || citedRef.filename || unknownLabel;
  if (!key) return unknownLabel;
  const m = key.match(/^(.+?)\s+p\.(\d+)\s+¶(\d+)/);
  if (m) {
    const name = (m[1] || "").replace(/\.[a-z0-9]+$/i, "");
    return `${name} p.${m[2]} ¶${m[3]}`;
  }
  return key;
}

/**
 * Single chat-scoped modal that listens to CitationDrawerContext.
 * Render exactly one of these inside `<CitationDrawerProvider>`,
 * somewhere outside the message list (typically right before
 * `</PageShell>`). All ChatBubble instances in the same provider
 * share this surface — clicking any chip anywhere in the chat opens
 * the same popup.
 */
import { useCitationDrawer } from "./CitationDrawerContext";
export function CitationPreviewSurface() {
  const { openRef, closeCitation } = useCitationDrawer();
  // NOTE: the prop is `citedRef`, not `ref` — see the file header for
  // why a prop literally named `ref` never reaches the component.
  return <CitationPreviewModal citedRef={openRef} onClose={closeCitation} />;
}
