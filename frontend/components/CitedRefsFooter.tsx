"use client";

/**
 * Stage 4: footer chip strip showing every cited source for a bot reply.
 *
 * The chips inside the bot's markdown answer are inline (handled by the
 * `citation` class in markdown.ts). This footer is the *summary list* —
 * one chip per unique chunk — so users can scan the source set without
 * hunting through the prose. Clicking either inline or footer chip
 * dispatches the same onOpen callback; the drawer state lives on the
 * parent (ChatBubble).
 */
import type { CitedRef } from "@/lib/api";

export function CitedRefsFooter({
  refs,
  onOpen,
}: {
  refs: CitedRef[];
  onOpen: (ref: CitedRef) => void;
}) {
  if (!refs || refs.length === 0) return null;
  // Dedupe by chunk_id so the same source cited twice in the prose
  // doesn't render two identical chips. Skip nullish entries that
  // would otherwise throw `Cannot read properties of undefined` at
  // render time — the parent stream occasionally emits a null entry
  // when a chunk lookup happens before the assistant JSON is parsed.
  const seen = new Set<number>();
  const uniq: CitedRef[] = [];
  for (const r of refs) {
    if (!r || typeof r.chunk_id !== "number") continue;
    if (seen.has(r.chunk_id)) continue;
    seen.add(r.chunk_id);
    uniq.push(r);
  }
  return (
    <div
      style={{
        marginTop: 6,
        paddingTop: 6,
        borderTop: "1px dashed var(--border)",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        fontSize: 11,
        color: "var(--fg-subtle)",
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 10px" }}>
        {uniq.map((r, i) => (
          <span
            key={r.chunk_id}
            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
          >
            <button
              type="button"
              onClick={() => onOpen(r)}
              title={r.snippet || r.filename}
              style={{
                border: "none",
                background: "transparent",
                color: "#92400E",
                fontWeight: 600,
                fontSize: 11,
                cursor: "pointer",
                padding: 0,
              }}
            >
              [{i + 1}]
            </button>
            <span
              style={{
                maxWidth: 220,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={r.citation_key || r.filename}
            >
              {(r.citation_key || r.filename || "未知来源").replace(/\.pdf$/i, "")}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}