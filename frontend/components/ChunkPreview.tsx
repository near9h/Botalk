"use client";

/**
 * Stage 2 / Stage 5: chunk list preview.
 *
 * Renders one row per `kb_chunks` row the backend mirrored locally.
 * Each row shows:
 *   - the page + paragraph number (when known)
 *   - a 200-char snippet preview
 *   - a "👁 预览" button that opens a *local* modal:
 *       ├─ left: PdfViewerWithBbox for the source PDF, scrolled to
 *       │        the chunk's page with a bbox highlight (if any)
 *       └─ right: the full chunk text + page/para/filename metadata
 *
 * Earlier this component forwarded clicks to the page-level
 * `CitationDrawerSurface` via `useCitationDrawer()`. The stub-fallback
 * in `CitationDrawerContext` ate the click silently because its
 * `openCitation` is a no-op when no Provider is mounted in the tree.
 * Doing the modal locally makes the preview behaviour predictable and
 * avoids leaking chat-only state into the KB surface.
 *
 * The bbox payload lives on the chunk row itself; we read it via
 * `kb_chunks.bbox_json` and convert to PDF user-space coords (the
 * backend already stores them in that coordinate space).
 */
import { useEffect, useState } from "react";
import type { KbChunk, KbDocument } from "@/lib/api";
import { api } from "@/lib/api";
import { PdfViewerWithBbox, type PdfHighlight } from "./PdfViewerWithBbox";

export function ChunkPreview({
  chunks,
  kbId,
  kbDocId,
  filename,
}: {
  chunks: KbChunk[];
  kbId: string;
  kbDocId: number;
  filename: string;
}) {
  const [active, setActive] = useState<KbChunk | null>(null);
  if (!chunks || chunks.length === 0) {
    return (
      <div
        style={{
          padding: 12,
          fontSize: 12,
          color: "var(--fg-subtle)",
          textAlign: "center",
          border: "1px dashed var(--border)",
          borderRadius: 8,
        }}
      >
        暂无 chunk（可能尚未完成解析）
      </div>
    );
  }
  return (
    <>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          maxHeight: 480,
          overflowY: "auto",
        }}
      >
        {chunks.map((c) => {
          const hasBbox = !!c.bbox_json && Array.isArray(c.bbox_json);
          return (
            <div
              key={c.id}
              onClick={() => setActive(c)}
              style={{
                display: "flex",
                gap: 10,
                padding: 10,
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                background: "var(--surface-solid)",
                fontSize: 12,
                alignItems: "flex-start",
                cursor: "pointer",
                transition: "background var(--transition)",
              }}
            >
              <div
                style={{
                  flexShrink: 0,
                  fontFamily: '"JetBrains Mono", monospace',
                  fontSize: 11,
                  color: "var(--fg-subtle)",
                  minWidth: 72,
                }}
              >
                {c.page != null ? `p.${c.page}` : "—"}
                {c.para != null ? ` ¶${c.para}` : ""}
              </div>
              <div
                style={{
                  flex: 1,
                  minWidth: 0,
                  lineHeight: 1.5,
                  color: "var(--fg)",
                  whiteSpace: "pre-wrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  display: "-webkit-box",
                  WebkitLineClamp: 3,
                  WebkitBoxOrient: "vertical",
                }}
                title={c.snippet}
              >
                {c.snippet || "（无内容）"}
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setActive(c);
                }}
                title={hasBbox ? "在 PDF 中定位" : "查看 chunk 详情"}
                aria-label="预览"
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  background: "var(--surface-2)",
                  cursor: "pointer",
                  fontSize: 13,
                  flexShrink: 0,
                }}
              >
                👁
              </button>
            </div>
          );
        })}
      </div>
      {active && (
        <ChunkPreviewModal
          chunk={active}
          kbId={kbId}
          kbDocId={kbDocId}
          filename={filename}
          onClose={() => setActive(null)}
        />
      )}
    </>
  );
}

/**
 * Modal that pairs a chunk row with its source PDF.
 *
 * Layout (left | right):
 *   - Left: PdfViewerWithBbox for the document, with a single
 *     bbox highlight at the chunk's page. Fetches the doc row to
 *     resolve `public_id` for the download URL.
 *   - Right: chunk metadata header (filename / page / para), the
 *     full chunk text wrapped in a scrollable container, and a
 *     "关闭" button.
 *
 * Why fetch `getKbDocument` lazily: the parent already has the doc
 * public_id for the active selection but the chunk row alone doesn't
 * carry it, and we want this modal to be self-contained so the chunk
 * list could one day be embedded elsewhere.
 */
function ChunkPreviewModal({
  chunk,
  kbId,
  kbDocId,
  filename,
  onClose,
}: {
  chunk: KbChunk;
  kbId: string;
  kbDocId: number;
  filename: string;
  onClose: () => void;
}) {
  const [doc, setDoc] = useState<KbDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bbox = (chunk.bbox_json as [number, number, number, number] | null) ?? null;

  // Esc closes the modal.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.getKbDocument(kbId, kbDocId);
        if (!cancelled) setDoc(d);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kbId, kbDocId]);

  // PdfViewerWithBbox accepts an `inline=1` query so the browser
  // renders the bytes inside an <iframe> instead of downloading.
  const pdfSrc = doc?.public_id
    ? `/api/attachments/${doc.public_id}/download?inline=1`
    : null;
  const highlights: PdfHighlight[] = bbox
    ? [{ page: chunk.page || 1, bbox, label: `p.${chunk.page ?? "?"} ¶${chunk.para ?? "?"}` }]
    : chunk.page
      ? [{ page: chunk.page, bbox: null, label: `p.${chunk.page}` }]
      : [];
  const isPdf = (doc?.mime_type || "").includes("pdf") || /\.pdf$/i.test(filename);

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(15, 23, 42, 0.35)",
          zIndex: 99,
        }}
      />
      <div
        role="dialog"
        aria-label="Chunk 预览"
        style={{
          position: "fixed",
          inset: "5vh 5vw",
          background: "var(--surface)",
          borderRadius: 12,
          boxShadow: "0 20px 60px rgba(15, 23, 42, 0.35)",
          zIndex: 100,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 16px",
            borderBottom: "1px solid var(--border)",
            background: "var(--surface-2)",
          }}
        >
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              🧩 Chunk #{chunk.id}
            </div>
            <div
              style={{
                fontSize: 12,
                color: "var(--fg-subtle)",
                marginTop: 2,
              }}
            >
              📄 {filename}
              {chunk.page != null ? ` · 第 ${chunk.page} 页` : ""}
              {chunk.para != null ? ` · 段落 ${chunk.para}` : ""}
              {!bbox && chunk.page != null ? " · 无 bbox（按页定位）" : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            style={{
              border: "1px solid var(--border)",
              background: "var(--surface)",
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

        {/* Body */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
            gap: 0,
            flex: 1,
            minHeight: 0,
          }}
        >
          {/* Left: PDF */}
          <div
            style={{
              borderRight: "1px solid var(--border)",
              background: "#f8fafc",
              overflow: "hidden",
              position: "relative",
            }}
          >
            {!doc ? (
              <div
                style={{
                  padding: 24,
                  fontSize: 13,
                  color: "var(--fg-subtle)",
                  textAlign: "center",
                }}
              >
                正在加载文档…
              </div>
            ) : error ? (
              <div
                style={{
                  padding: 24,
                  fontSize: 13,
                  color: "#991B1B",
                  textAlign: "center",
                }}
              >
                加载文档失败：{error}
              </div>
            ) : !isPdf ? (
              <div
                style={{
                  padding: 24,
                  fontSize: 13,
                  color: "var(--fg-subtle)",
                  textAlign: "center",
                }}
              >
                当前文件不是 PDF，无法在浏览器内预览。
              </div>
            ) : pdfSrc ? (
              <PdfViewerWithBbox
                src={pdfSrc}
                highlights={highlights}
                title={filename}
                width={720}
              />
            ) : (
              <div
                style={{
                  padding: 24,
                  fontSize: 13,
                  color: "#991B1B",
                  textAlign: "center",
                }}
              >
                该文档缺少 public_id，无法在线预览。
              </div>
            )}
          </div>

          {/* Right: chunk text */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
              background: "var(--surface)",
            }}
          >
            <div
              style={{
                padding: "10px 16px",
                fontSize: 12,
                fontWeight: 600,
                color: "var(--fg-muted)",
                borderBottom: "1px solid var(--border)",
                background: "var(--surface-2)",
              }}
            >
              chunk 内容
            </div>
            <div
              style={{
                padding: 16,
                fontSize: 13,
                lineHeight: 1.7,
                color: "var(--fg)",
                whiteSpace: "pre-wrap",
                overflowY: "auto",
                flex: 1,
              }}
            >
              {chunk.snippet || "（无内容）"}
            </div>
            {bbox && (
              <div
                style={{
                  padding: "10px 16px",
                  borderTop: "1px solid var(--border)",
                  fontSize: 11,
                  color: "var(--fg-subtle)",
                  background: "var(--surface-2)",
                }}
              >
                bbox (PDF user-space)：[
                {bbox.map((n) => n.toFixed(1)).join(", ")}
                ]
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
