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
import { CitationChip } from "./SourceCitation";

export function CitedRefsFooter({
  refs,
  onOpen,
}: {
  refs: CitedRef[];
  onOpen: (ref: CitedRef) => void;
}) {
  if (!refs || refs.length === 0) return null;
  // Dedupe by chunk_id so the same source cited twice in the prose
  // doesn't render two identical chips.
  const seen = new Set<number>();
  const uniq: CitedRef[] = [];
  for (const r of refs) {
    if (seen.has(r.chunk_id)) continue;
    seen.add(r.chunk_id);
    uniq.push(r);
  }
  return (
    <div
      style={{
        marginTop: 8,
        paddingTop: 8,
        borderTop: "1px dashed var(--border)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
          color: "var(--fg-subtle)",
        }}
      >
        <span>📚 来源</span>
        <span style={{ fontFamily: '"JetBrains Mono", monospace' }}>
          {uniq.length}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        {uniq.map((r) => (
          <CitationChip key={r.chunk_id} ref={r} onOpen={onOpen} />
        ))}
      </div>
    </div>
  );
}