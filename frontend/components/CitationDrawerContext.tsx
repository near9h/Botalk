"use client";

/**
 * Stage 4 fix: cross-bubble citation drawer state.
 *
 * The first cut kept the `openRef` state inside each `ChatBubble` —
 * but the chat page renders one ChatBubble per message, so clicking a
 * citation chip in bubble B while the drawer was opened by bubble A
 * silently did nothing (bubble B's local `openRef` was `null`).
 *
 * The fix: hoist the drawer state to the chat page via a React
 * Context. Every ChatBubble reads the current `openRef` from context
 * and writes through `openCitation`. The single drawer instance is
 * rendered by the chat page itself, not by every ChatBubble — so
 * there's exactly one viewer in the DOM, no matter how many bubbles.
 *
 * `useCitationDrawer()` is the consumer hook. Chat pages wrap their
 * subtree in `<CitationDrawerProvider>` once and render one
 * `<CitationPreviewSurface />` at the end.
 */
import { createContext, ReactNode, useCallback, useContext, useMemo, useState } from "react";
import type { CitedRef } from "@/lib/api";

type CitationCtx = {
  openRef: CitedRef | null;
  openCitation: (ref: CitedRef) => void;
  closeCitation: () => void;
};

const Ctx = createContext<CitationCtx | null>(null);

export function CitationDrawerProvider({ children }: { children: ReactNode }) {
  const [openRef, setOpenRef] = useState<CitedRef | null>(null);
  const openCitation = useCallback((ref: CitedRef) => setOpenRef(ref), []);
  const closeCitation = useCallback(() => setOpenRef(null), []);
  const value = useMemo(
    () => ({ openRef, openCitation, closeCitation }),
    [openRef, openCitation, closeCitation],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCitationDrawer(): CitationCtx {
  const v = useContext(Ctx);
  if (!v) {
    // Safe fallback: a no-op drawer so callers rendered outside the
    // provider don't crash. The drawer surface (rendered by the
    // provider's parent) is still what controls visibility, so the
    // worst case is "clicking a citation does nothing visible" —
    // not a runtime error.
    return {
      openRef: null,
      openCitation: () => {},
      closeCitation: () => {},
    };
  }
  return v;
}