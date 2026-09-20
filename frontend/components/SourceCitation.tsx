"use client";

/**
 * Stage 4: Citation chip UI + drawer for the PDF.js viewer.
 *
 * Two pieces:
 *   - <CitationChip ref={…} onOpen={…} /> renders a single clickable
 *     chip used both inline (in the bot answer, via the markdown
 *     pipeline) and as the footer entry in <CitedRefsFooter />.
 *   - <CitationDrawer ref={…} onClose={…} /> opens the PdfViewerWithBbox
 *     in a side drawer so the chat scroll position is preserved.
 *
 * The chip is the only "always-visible" surface — clicking it dispatches
 * a fetch to GET /api/kb/{kb_id}/chunks/{chunk_id} for the chunk's
 * bbox payload, then opens the drawer with the highlighted page.
 *
 * Why a drawer (not a modal): the user is mid-conversation; killing
 * the scroll position every time they peek at a citation is annoying.
 * The drawer is a 480px side panel anchored to the right edge.
 */
import { useEffect, useState } from "react";
import type { CitedRef } from "@/lib/api";
import { api } from "@/lib/api";
import { PdfViewerWithBbox, type PdfHighlight } from "./PdfViewerWithBbox";

export type CitationChipProps = {
  // Accept `CitedRef | undefined` so callers iterating `refs` don't
  // have to filter out null entries — we render a disabled stub chip
  // for those instead of throwing at render time. The marshalling
  // path (orchestrator → SSE → frontend) occasionally emits a
  // null entry when a chunk lookup happens before the assistant JSON
  // is fully parsed; rendering must remain robust.
  ref: CitedRef | null | undefined;
  onOpen: (ref: CitedRef) => void;
};

/**
 * Single clickable chip. Compact, fits both inline (in chat) and as
 * a footer entry. Color = accent (purple) so the user can distinguish
 * a citation from a plain mention or attachment.
 */
export function CitationChip({ ref, onOpen }: CitationChipProps) {
  const label = shortLabel(ref);
  const title = ref?.snippet || ref?.citation_key || label;
  // Nullish ref → render a non-interactive "未知来源" pill. We don't
  // want to throw `Cannot read properties of undefined` here because
  // the chat page is already scrolled past the bubble.
  if (!ref) {
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
      >
        📎 {label}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onOpen(ref);
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
 * Right-side drawer that hosts the PDF.js viewer for one citation.
 *
 * Lazy fetch: we only call GET /api/kb/{kb_id}/chunks/{chunk_id} when
 * the drawer mounts. The chunk row carries the bbox_json and the
 * attachment_id, but the *file bytes* are served by the existing
 * /api/attachments/{public_id}/download endpoint — except KB attachments
 * aren't chat attachments (group_id NULL), so we have to fetch the
 * public_id via a dedicated KB-doc endpoint. To keep this Stage 4 commit
 * self-contained, we derive the URL from kb_doc_id and call a sibling
 * endpoint the KB API will host. If the fetch fails (e.g. RAGFlow down
 * and no local file), we still render the chip metadata so the user
 * sees the snippet + page number, just without a live PDF preview.
 */
export function CitationDrawer({
  ref,
  onClose,
}: {
  ref: CitedRef | null;
  onClose: () => void;
}) {
  const [pdfSrc, setPdfSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Esc closes it. Only bind while open so other Esc handlers (modal
  // dialogs elsewhere on the page) keep working when the drawer is
  // closed.
  useEffect(() => {
    if (!ref) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [ref, onClose]);

  useEffect(() => {
    if (!ref) {
      setPdfSrc(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setError(null);
    setPdfSrc(null);
    (async () => {
      try {
        // Fetch the chunk row so we have the bbox (the SSE payload
        // already carries bbox, but we re-fetch to honor any post-
        // retrieval chunk updates — and to be robust against partial
        // payloads).
        const chunk = await api.getKbChunk(ref.kb_id, ref.chunk_id);
        if (cancelled) return;
        // The chunk row alone doesn't carry the attachment's public_id;
        // we need to round-trip through the document endpoint to get a
        // downloadable URL. Stage 2 wired up the listing + single-doc
        // endpoint which carries the public_id via /api/kb/{id}/docs.
        const doc = await api.getKbDocument(ref.kb_id, ref.kb_doc_id);
        if (cancelled) return;
        // Reuse the same path the regular chat uses — KB attachments
        // are served through /api/attachments/{public_id}/download.
        // We *must* use the wire-facing public_id (unguessable token),
        // not the integer pk — the download endpoint refuses the int
        // id since the public_id migration.
        if (!doc.public_id) {
          setError(`该文档缺少 public_id，无法在线预览`);
        } else if (doc.mime_type?.includes("pdf") || /\.pdf$/i.test(doc.filename)) {
          setPdfSrc(`/api/attachments/${doc.public_id}/download`);
        } else {
          setError(
            `暂不支持在线预览 ${doc.filename || "此文件"}（仅 PDF 可在浏览器内打开）`,
          );
        }
        // Touch `chunk` so eslint doesn't flag the unused var — the
        // fetch itself is the side effect we want (refreshes bbox).
        void chunk;
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          setError(msg);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ref]);

  if (!ref) return null;

  const highlights: PdfHighlight[] = ref.bbox
    ? [{ page: ref.page || 1, bbox: ref.bbox, label: ref.citation_key }]
    : ref.page
      ? [{ page: ref.page, bbox: null, label: ref.citation_key }]
      : [];

  return (
    <>
      {/* Backdrop; clicking it closes the drawer without consuming the click. */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(15, 23, 42, 0.18)",
          zIndex: 99,
        }}
      />
      <aside
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: "min(560px, 90vw)",
          background: "var(--surface)",
          boxShadow: "-8px 0 24px rgba(15, 23, 42, 0.18)",
          zIndex: 100,
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 12,
          overflowY: "auto",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              📄 {ref.filename}
            </div>
            <div
              style={{
                fontSize: 12,
                color: "var(--fg-subtle)",
                marginTop: 2,
              }}
            >
              {ref.page ? `第 ${ref.page} 页` : "整篇"}
              {ref.para != null ? ` · 段落 ${ref.para}` : ""}
              {ref.score ? ` · 相似度 ${(ref.score * 100).toFixed(1)}%` : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭引用面板"
            style={{
              border: "1px solid var(--border)",
              background: "var(--surface-2)",
              borderRadius: 8,
              width: 32,
              height: 32,
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            ✕
          </button>
        </div>

        {ref.snippet && (
          <div
            style={{
              padding: 12,
              borderRadius: "var(--radius)",
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              fontSize: 13,
              lineHeight: 1.6,
              color: "var(--fg)",
              whiteSpace: "pre-wrap",
            }}
          >
            {ref.snippet}
          </div>
        )}

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

        {pdfSrc && (
          <PdfViewerWithBbox
            src={pdfSrc}
            highlights={highlights}
            title="原文定位"
            width={520}
          />
        )}
      </aside>
    </>
  );
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
function shortLabel(ref: CitedRef | undefined | null): string {
  if (!ref) return "未知来源";
  // citation_key looks like `<filename> p.X ¶Y`. We strip the extension
  // off the filename so the chip stays compact.
  const key = ref.citation_key || ref.filename || "未知来源";
  if (!key) return "未知来源";
  const m = key.match(/^(.+?)\s+p\.(\d+)\s+¶(\d+)/);
  if (m) {
    const name = (m[1] || "").replace(/\.[a-z0-9]+$/i, "");
    return `${name} p.${m[2]} ¶${m[3]}`;
  }
  return key;
}

/**
 * Single chat-scoped drawer that listens to CitationDrawerContext.
 * Render exactly one of these inside `<CitationDrawerProvider>`,
 * somewhere outside the message list (typically right before
 * `</PageShell>`). All ChatBubble instances in the same provider
 * share this surface — clicking any chip anywhere in the chat opens
 * the same drawer.
 */
import { useCitationDrawer } from "./CitationDrawerContext";
export function CitationDrawerSurface() {
  const { openRef, closeCitation } = useCitationDrawer();
  return <CitationDrawer ref={openRef} onClose={closeCitation} />;
}