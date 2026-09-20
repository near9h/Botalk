"use client";

/**
 * Stage 4: PDF.js + bbox overlay viewer.
 *
 * Why we own this component instead of pulling a third-party `<PdfViewer />`:
 *   - pdfjs-dist's worker URL needs careful handling in Next.js (it's an
 *     .mjs file under `node_modules`); we wire it up via dynamic import
 *     so it never lands in the SSR bundle.
 *   - We need a tight bbox overlay — the chat layer hands us
 *     `{page, bbox: [x1,y1,x2,y2]}` from a `cited_refs` entry and we
 *     have to light up exactly that rectangle. Wrapping an off-the-shelf
 *     viewer would force us to crack open its internals; rendering to a
 *     plain `<canvas>` keeps the API surface honest.
 *
 * PDF source: we accept a `src: string` (URL or blob URL) plus a
 * `highlights: Array<{page, bbox, label?}>` payload. The viewer jumps to
 * the first highlight's page on mount and draws a translucent yellow
 * rectangle on top of every page in `highlights`. Subsequent highlight
 * changes (e.g. user clicks a different chip in the chat) update the
 * overlay without re-rendering the PDF.
 *
 * Worker resolution: pdfjs-dist 4.x ships `pdf.worker.min.mjs`. We point
 * `GlobalWorkerOptions.workerSrc` at the bundled file via dynamic import
 * URL. The build must NOT pre-bundle this module (hence the dynamic
 * `import('pdfjs-dist')` inside `useEffect`).
 */
import { useEffect, useRef, useState } from "react";

export type PdfHighlight = {
  /** 1-indexed page number (matches backend `kb_chunks.page`). */
  page: number;
  /** [x1, y1, x2, y2] in PDF user-space coordinates (origin bottom-left). */
  bbox: [number, number, number, number] | null;
  /** Optional chip label rendered in the overlay corner. */
  label?: string;
};

type Props = {
  src: string;
  highlights: PdfHighlight[];
  /** Render at this CSS pixel width; the viewer auto-scales the height. */
  width?: number;
  /** Optional title shown above the canvas. */
  title?: string;
  /** Called when the user clicks the close button. */
  onClose?: () => void;
};

type PdfDoc = {
  numPages: number;
  getPage: (n: number) => Promise<PdfPage>;
};

type PdfPage = {
  getViewport: (opts: { scale: number }) => { width: number; height: number };
  render: (opts: { canvasContext: CanvasRenderingContext2D; viewport: unknown }) => {
    promise: Promise<void>;
  };
};

export function PdfViewerWithBbox({
  src,
  highlights,
  width = 720,
  title,
  onClose,
}: Props) {
  const [pdf, setPdf] = useState<PdfDoc | null>(null);
  const [pageNumber, setPageNumber] = useState<number>(1);
  const [numPages, setNumPages] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  // Canvas pixel size + the scale used to render it. `bbox` arrives in
  // PDF user-space (scale = 1), so the overlay MUST multiply by this
  // scale before placing rectangles, otherwise the highlight drifts
  // further off the lower/right the more the page is zoomed.
  const [view, setView] = useState<{
    page: number;
    width: number;
    height: number;
    scale: number;
  } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);

  // Jump to the first highlight's page whenever the highlights array
  // changes (e.g. user clicked a different citation chip).
  useEffect(() => {
    if (highlights.length > 0) {
      const target = Math.max(1, Math.min(highlights[0].page || 1, numPages || 1));
      setPageNumber(target);
    }
  }, [highlights, numPages]);

  // Load pdfjs once on mount and load the document. We dynamically
  // import so the heavy worker module never lands in the SSR bundle.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        // Resolve worker URL. Next.js bundles `node_modules/pdfjs-dist`
        // at build time; we point the worker at the same version's
        // .mjs file via `new URL(...)`. Falls back to CDN if the
        // bundler stripped the import (e.g. standalone Docker build).
        try {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const workerUrl: string = (pdfjs as any).GlobalWorkerOptions.workerSrc ?? "";
          if (!workerUrl) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (pdfjs as any).GlobalWorkerOptions.workerSrc = new URL(
              "pdfjs-dist/build/pdf.worker.min.mjs",
              import.meta.url,
            ).toString();
          }
        } catch {
          // Last-resort CDN; the chat still works on the main thread
          // (slower but functional).
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (pdfjs as any).GlobalWorkerOptions.workerSrc =
            `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${(pdfjs as any).version}/pdf.worker.min.mjs`;
        }
        const loadingTask = pdfjs.getDocument(src);
        const doc = await loadingTask.promise;
        if (cancelled) return;
        setPdf(doc as unknown as PdfDoc);
        setNumPages(doc.numPages);
        if (highlights.length > 0 && highlights[0].page) {
          setPageNumber(Math.max(1, Math.min(highlights[0].page, doc.numPages)));
        }
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          setError(msg || "PDF 加载失败");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // We deliberately exclude `highlights` here — the effect only
    // loads the doc once. Page-jumping is handled by the other effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  // Re-render the current page whenever pdf / pageNumber changes.
  useEffect(() => {
    if (!pdf || !canvasRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        const page = await pdf.getPage(pageNumber);
        if (cancelled) return;
        const containerWidth = width;
        const naturalViewport = page.getViewport({ scale: 1 });
        const scale = containerWidth / naturalViewport.width;
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current!;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        // Sync the overlay container to the same size so bbox rectangles
        // align pixel-for-pixel with the rendered page.
        if (overlayRef.current) {
          overlayRef.current.style.width = `${canvas.width}px`;
          overlayRef.current.style.height = `${canvas.height}px`;
        }
        await page.render({ canvasContext: ctx, viewport }).promise;
        if (cancelled) return;
        // Publish the rendered size + scale so the overlay can convert
        // PDF user-space bbox coords into canvas pixels.
        setView({
          page: pageNumber,
          width: canvas.width,
          height: canvas.height,
          scale,
        });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg || "PDF 渲染失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pdf, pageNumber, width]);

  const highlightsOnPage = highlights.filter((h) => h.page === pageNumber);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        background: "var(--surface-solid)",
        borderRadius: "var(--radius)",
        border: "1px solid var(--border)",
        padding: 12,
      }}
    >
      {(title || onClose) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              style={{
                border: "1px solid var(--border)",
                background: "var(--surface-2)",
                borderRadius: 8,
                width: 28,
                height: 28,
                cursor: "pointer",
                fontSize: 13,
              }}
            >
              ✕
            </button>
          )}
        </div>
      )}
      {error ? (
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
      ) : (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12,
              color: "var(--fg-subtle)",
            }}
          >
            <button
              type="button"
              onClick={() => setPageNumber((n) => Math.max(1, n - 1))}
              disabled={pageNumber <= 1}
              style={navBtn}
            >
              ←
            </button>
            <span style={{ fontFamily: '"JetBrains Mono", monospace' }}>
              第 {pageNumber} / {numPages || "?"} 页
            </span>
            <button
              type="button"
              onClick={() =>
                setPageNumber((n) => Math.min(numPages || n, n + 1))
              }
              disabled={pageNumber >= numPages}
              style={navBtn}
            >
              →
            </button>
            {highlightsOnPage.length > 0 && (
              <span
                style={{
                  marginLeft: 8,
                  padding: "2px 8px",
                  background: "rgba(250, 204, 21, 0.18)",
                  color: "#854D0E",
                  borderRadius: 999,
                  fontSize: 11,
                }}
              >
                {highlightsOnPage.length} 处高亮
              </span>
            )}
          </div>
          <div
            style={{
              position: "relative",
              overflow: "auto",
              maxHeight: "70vh",
              borderRadius: 8,
              background: "#fff",
              border: "1px solid var(--border)",
            }}
          >
            <canvas ref={canvasRef} style={{ display: "block" }} />
            <div
              ref={overlayRef}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                pointerEvents: "none",
              }}
            >
              {view?.page === pageNumber &&
                highlightsOnPage.map((h, idx) =>
                  h.bbox ? (
                    <PdfBboxOverlay
                      key={idx}
                      bbox={h.bbox}
                      label={h.label}
                      scale={view.scale}
                      pageHeight={view.height}
                    />
                  ) : null,
                )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const navBtn: React.CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--surface-2)",
  cursor: "pointer",
  fontSize: 12,
};

/**
 * Render one bbox rectangle on top of the rendered PDF page.
 *
 * Coordinate space:
 *   - the bbox arrives in PDF user-space coords (origin at bottom-left,
 *     y axis pointing up, scale = 1) — i.e. the raw page units.
 *   - our canvas is rendered at `scale` and painted top-down with origin
 *     at top-left.
 *   - so we first scale every component, then flip y:
 *     `canvasY = pageHeight - pdfY * scale`.
 *
 * Forgetting the `scale` factor is what makes the highlight drift: the
 * canvas grows with the container while the bbox stays in page units.
 */
function PdfBboxOverlay({
  bbox,
  label,
  scale,
  pageHeight,
}: {
  bbox: [number, number, number, number];
  label?: string;
  scale: number;
  pageHeight: number;
}) {
  const [x1, y1, x2, y2] = bbox;
  const left = Math.min(x1, x2) * scale;
  const right = Math.max(x1, x2) * scale;
  const top = pageHeight - Math.max(y1, y2) * scale;
  const height = Math.abs(y2 - y1) * scale;
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width: right - left,
        height,
        background: "rgba(250, 204, 21, 0.30)",
        border: "2px solid rgba(217, 119, 6, 0.85)",
        borderRadius: 4,
        boxSizing: "border-box",
        boxShadow: "0 0 0 4px rgba(250, 204, 21, 0.12)",
      }}
      data-pdf-bbox
    >
      {label && (
        <span
          style={{
            position: "absolute",
            top: -22,
            left: 0,
            background: "rgba(217, 119, 6, 0.95)",
            color: "white",
            padding: "2px 8px",
            borderRadius: 6,
            fontSize: 11,
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
      )}
    </div>
  );
}