"use client";

/**
 * Stage 2 / Stage 5: chunk list preview.
 *
 * Renders one row per `kb_chunks` row the backend mirrored locally.
 * Each row shows:
 *   - the page + paragraph number (when known)
 *   - a 200-char snippet preview
 *   - a "👁 预览" button that opens the PdfViewerWithBbox drawer
 *
 * The bbox payload lives on the chunk row itself; we read it via
 * `kb_chunks.bbox_json` and convert to PDF user-space coords
 * (the backend already stores them in that coordinate space).
 */
import { useState } from "react";
import type { KbChunk } from "@/lib/api";
import { CitationDrawer } from "./SourceCitation";
import { useCitationDrawer } from "./CitationDrawerContext";
import type { CitedRef } from "@/lib/api";

export function ChunkPreview({
  chunks,
  kbId,
  kbDocId,
  filename,
  onClose,
}: {
  chunks: KbChunk[];
  kbId: number;
  kbDocId: number;
  filename: string;
  onClose?: () => void;
}) {
  const [active, setActive] = useState<CitedRef | null>(null);
  // Use the shared drawer surface when available (i.e. KB detail page
  // wrapped in CitationDrawerProvider). Fall back to a locally
  // rendered drawer when the consumer didn't wrap — e.g. embedded
  // previews in other pages.
  const drawerCtx = useCitationDrawer();
  const usingSharedSurface = drawerCtx.openCitation !== undefined;
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
          const bbox = (c.bbox_json as [number, number, number, number] | null) ?? null;
          const ref: CitedRef = {
            chunk_id: c.id,
            kb_id: kbId,
            kb_doc_id: kbDocId,
            filename,
            page: c.page,
            para: c.para,
            bbox,
            snippet: c.snippet,
            score: 0,
            ragflow_chunk_id: c.ragflow_chunk_id,
            citation_key: `${filename} p.${c.page ?? "?"} ¶${c.para ?? "?"}`,
          };
          return (
            <div
              key={c.id}
              style={{
                display: "flex",
                gap: 10,
                padding: 10,
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                background: "var(--surface-solid)",
                fontSize: 12,
                alignItems: "flex-start",
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
                onClick={() => {
                  if (usingSharedSurface) {
                    drawerCtx.openCitation(ref);
                  } else {
                    setActive(ref);
                  }
                }}
                title="在 PDF 中定位"
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
      {/* KB detail page renders a shared CitationDrawerSurface at the
          chat-page level, so when one is in scope we hand the click
          to that surface and skip the local drawer entirely. The
          fallback path renders a per-component drawer for embeds
          that aren't wrapped. */}
      {!usingSharedSurface && (
        <CitationDrawer
          ref={active}
          onClose={() => {
            setActive(null);
            onClose?.();
          }}
        />
      )}
    </>
  );
}