"use client";

/**
 * Right-side drawer for previewing attachment bytes inline.
 *
 * Goals:
 *   - KIMI-style "click preview, drawer opens, content shows" UX
 *   - Zero new npm dependencies — only browser-native rendering and the
 *     markdown-it instance already used elsewhere in the app
 *   - Sandbox the previewed content: anything coming from the network
 *     lives inside an `iframe sandbox` so a bot that emits hostile HTML
 *     can't reach into the parent app.
 *
 * Renderers by mime:
 *   - text/markdown, .md       → markdown-it → HTML in iframe sandbox
 *   - text/html,  .html/.htm   → iframe sandbox srcdoc
 *   - application/pdf, .pdf    → <iframe src={pdfUrl}> (browser built-in viewer)
 *   - text/*                    → <pre> inside iframe sandbox
 *   - image/*                   → <img> (only file types the browser
 *                                  natively understands)
 *   - everything else (docx, xlsx, pptx, …) → "no in-page preview
 *                                  available, please download" hint
 *                                  with a primary download button.
 */

import { useEffect, useMemo, useState } from "react";
import { md } from "@/lib/markdown";
import { AttachmentMeta } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Props = {
  attachment: AttachmentMeta;
  onClose: () => void;
};

function classify(att: AttachmentMeta):
  | "markdown"
  | "html"
  | "pdf"
  | "image"
  | "text"
  | "binary" {
  const ext = (att.filename ?? "").toLowerCase().split(".").pop() || "";
  const m = (att.mime_type ?? "").toLowerCase();
  if (["md", "markdown"].includes(ext) || m === "text/markdown") return "markdown";
  if (["html", "htm"].includes(ext) || m === "text/html") return "html";
  if (ext === "pdf" || m === "application/pdf") return "pdf";
  if (m.startsWith("image/") || ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext))
    return "image";
  if (m.startsWith("text/") || ["txt", "log", "json", "csv", "xml", "yml", "yaml"].includes(ext))
    return "text";
  return "binary";
}

function formatBytes(n: number | undefined): string {
  if (!n || n <= 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

// Sentinel values used to track fetch status without leaning on the
// user-visible Chinese string. The drawer cares about three phases:
// still loading, succeeded, or failed. We carry those as strings and
// map them to the right t() at render time.
const ATTACH_LOADING = "__ATTACH_LOADING__";
const ATTACH_FAILED = "__ATTACH_FAILED__";

/** Wrap rendered HTML in a minimal page that follows the host app's
 *  CSS variables, with safe defaults for markdown / report bodies. */
function wrapHtml(bodyHtml: string): string {
  return `<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root {
    color-scheme: light dark;
    --fg: #1f2328;
    --fg-subtle: #6b7280;
    --border: #e5e7eb;
    --accent: #6366f1;
    --surface: #ffffff;
    --code-bg: #f4f4f5;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --fg: #e6e6e6;
      --fg-subtle: #9ca3af;
      --border: #374151;
      --accent: #a78bfa;
      --surface: #111827;
      --code-bg: #1f2937;
    }
  }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    font-size: 14px;
    line-height: 1.7;
    color: var(--fg);
    background: var(--surface);
    padding: 24px 32px;
    word-break: break-word;
  }
  h1, h2, h3, h4 { line-height: 1.3; margin: 1.4em 0 .6em; }
  h1 { font-size: 1.6em; border-bottom: 1px solid var(--border); padding-bottom: .3em; }
  h2 { font-size: 1.35em; }
  h3 { font-size: 1.15em; }
  p { margin: .6em 0; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  code {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    background: var(--code-bg);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: .9em;
  }
  pre {
    background: var(--code-bg);
    padding: 14px 16px;
    border-radius: 8px;
    overflow-x: auto;
    line-height: 1.5;
  }
  pre code { background: transparent; padding: 0; }
  blockquote {
    margin: .8em 0;
    padding: .4em 1em;
    border-left: 4px solid var(--accent);
    color: var(--fg-subtle);
    background: rgba(99,102,241,.05);
  }
  table {
    border-collapse: collapse;
    margin: 1em 0;
    width: 100%;
  }
  th, td {
    border: 1px solid var(--border);
    padding: 6px 10px;
    text-align: left;
  }
  th { background: var(--code-bg); }
  img { max-width: 100%; height: auto; }
  hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
  ul, ol { padding-left: 1.6em; }
</style>
</head><body>${bodyHtml}</body></html>`;
}

export function AttachmentPreviewDrawer({ attachment, onClose }: Props) {
  const { t } = useI18n();
  const kind = classify(attachment);
  const [bodyText, setBodyText] = useState<string | null>(
    kind === "markdown" || kind === "html" || kind === "text" ? ATTACH_LOADING : null,
  );
  const [imgError, setImgError] = useState(false);

  const inlineUrl = useMemo(
    () => `/api/attachments/${attachment.public_id}/download?inline=1`,
    [attachment.public_id],
  );
  const downloadUrl = useMemo(
    () => `/api/attachments/${attachment.public_id}/download`,
    [attachment.public_id],
  );

  useEffect(() => {
    // Only need to read the body ourselves for kinds that don't have a
    // native browser renderer and aren't an image. PDF, image, and
    // binary types can ride straight through `inlineUrl` / `downloadUrl`.
    if (kind === "image" || kind === "pdf" || kind === "binary") return;
    let cancelled = false;
    fetch(inlineUrl)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((text) => {
        if (!cancelled) setBodyText(text);
      })
      .catch((e) => {
        if (!cancelled) setBodyText(`${ATTACH_FAILED}:${e instanceof Error ? e.message : String(e)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [inlineUrl, kind]);

  // ESC closes the drawer (KIMI-style)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  let body: React.ReactNode;
  if (kind === "pdf") {
    body = (
      <iframe
        title={attachment.filename}
        src={inlineUrl}
        style={iframeStyle}
      />
    );
  } else if (kind === "image") {
    body = imgError ? (
      <div style={fallbackStyle}>{t("attachment.imageLoadFail")}</div>
    ) : (
      <div style={{ padding: 24, textAlign: "center", overflow: "auto", height: "100%" }}>
        <img
          src={inlineUrl}
          alt={attachment.filename}
          style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
          onError={() => setImgError(true)}
        />
      </div>
    );
  } else if (kind === "markdown") {
    if (bodyText === ATTACH_LOADING) {
      body = <div style={fallbackStyle}>{t("common.loading")}</div>;
    } else if (bodyText && bodyText.startsWith(ATTACH_FAILED)) {
      body = <div style={fallbackStyle}>{t("attachment.loadFailFmt", { err: bodyText.slice(ATTACH_FAILED.length + 1) })}</div>;
    } else {
      // Render via the existing markdown-it singleton, then sandbox.
      // `html:false` keeps bot output from injecting script tags; we
      // still wrap it in a sandboxed iframe as belt-and-suspenders.
      const html = md.render(bodyText || "");
      body = (
        <iframe
          title={attachment.filename}
          srcDoc={wrapHtml(html)}
          sandbox=""
          style={iframeStyle}
        />
      );
    }
  } else if (kind === "html") {
    if (bodyText === ATTACH_LOADING) {
      body = <div style={fallbackStyle}>{t("common.loading")}</div>;
    } else if (bodyText && bodyText.startsWith(ATTACH_FAILED)) {
      body = <div style={fallbackStyle}>{t("attachment.loadFailFmt", { err: bodyText.slice(ATTACH_FAILED.length + 1) })}</div>;
    } else {
      // Raw HTML — sandbox it so the embedded doc can't phish cookies
      // or scrolljack the host app.
      body = (
        <iframe
          title={attachment.filename}
          srcDoc={bodyText || ""}
          sandbox="allow-same-origin"
          style={iframeStyle}
        />
      );
    }
  } else if (kind === "text") {
    body = bodyText === ATTACH_LOADING ? (
      <div style={fallbackStyle}>{t("common.loading")}</div>
    ) : bodyText && bodyText.startsWith(ATTACH_FAILED) ? (
      <div style={fallbackStyle}>{t("attachment.loadFailFmt", { err: bodyText.slice(ATTACH_FAILED.length + 1) })}</div>
    ) : (
      <pre style={preStyle}>{bodyText ?? ""}</pre>
    );
  } else {
    // docx / xlsx / pptx / unknown binary — the in-page preview is
    // intentionally not built. Give a friendly fallback with the
    // primary action (download) so the user isn't stuck.
    body = (
      <div style={fallbackStyle}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>
          {((attachment.filename ?? "")).toLowerCase().endsWith(".docx") ? "📄"
            : ((attachment.filename ?? "")).toLowerCase().endsWith(".xlsx") ? "📊"
            : ((attachment.filename ?? "")).toLowerCase().endsWith(".pptx") ? "📑"
            : "📎"}
        </div>
        <div style={{ fontSize: 14, color: "var(--fg)", marginBottom: 6 }}>
          {t("attachment.unsupported")}
        </div>
        <div style={{ fontSize: 12, color: "var(--fg-subtle)", marginBottom: 16 }}>
          {t("attachment.openHint")}
        </div>
        <a
          href={downloadUrl}
          download
          style={{
            display: "inline-block",
            padding: "8px 18px",
            background: "var(--accent)",
            color: "#fff",
            borderRadius: 8,
            textDecoration: "none",
            fontSize: 14,
          }}
        >
          {t("attachment.downloadFmt", { name: attachment.filename ?? t("attachment.untitled") })}
        </a>
      </div>
    );
  }

  return (
    <>
      <div onClick={onClose} style={backdropStyle} aria-hidden />
      <aside
        role="dialog"
        aria-label={t("attachment.previewAriaFmt", { name: attachment.filename ?? "" })}
        style={drawerStyle}
      >
        <header style={headerStyle}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              title={attachment.filename}
              style={{
                fontSize: 14,
                fontWeight: 600,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {attachment.filename}
            </div>
            <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2 }}>
              {formatBytes(attachment.size_bytes)}
              {" · "}
              {attachment.mime_type || t("attachment.unknownType")}
            </div>
          </div>
          <a
            href={downloadUrl}
            download
            style={iconBtnStyle}
            title={t("attachment.downloadTitle")}
            aria-label={t("attachment.downloadAria")}
          >
            ⬇
          </a>
          <button
            onClick={onClose}
            style={iconBtnStyle}
            title={t("attachment.close")}
            aria-label={t("attachment.closeAria")}
          >
            ✕
          </button>
        </header>
        <div style={bodyContainerStyle}>{body}</div>
      </aside>
    </>
  );
}

const backdropStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(15, 23, 42, 0.35)",
  zIndex: 80,
  animation: "fadeIn .15s ease",
};

const drawerStyle: React.CSSProperties = {
  position: "fixed",
  top: 0,
  right: 0,
  height: "100vh",
  width: "min(720px, 92vw)",
  background: "var(--surface)",
  borderLeft: "1px solid var(--border)",
  boxShadow: "-12px 0 32px rgba(0,0,0,0.18)",
  zIndex: 81,
  display: "flex",
  flexDirection: "column",
  animation: "slideInRight .2s ease",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "12px 16px",
  borderBottom: "1px solid var(--border)",
  background: "var(--surface-solid)",
  flexShrink: 0,
};

const iconBtnStyle: React.CSSProperties = {
  width: 32,
  height: 32,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--fg)",
  cursor: "pointer",
  fontSize: 14,
  textDecoration: "none",
};

const bodyContainerStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  position: "relative",
  background: "var(--surface)",
};

const iframeStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  border: "none",
  display: "block",
};

const fallbackStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  height: "100%",
  padding: 24,
  textAlign: "center",
  color: "var(--fg-subtle)",
};

const preStyle: React.CSSProperties = {
  margin: 0,
  padding: 24,
  height: "100%",
  overflow: "auto",
  fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  fontSize: 13,
  lineHeight: 1.6,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  color: "var(--fg)",
};