"use client";

/**
 * Stage 5: Knowledge Base detail page.
 *
 * Surface area:
 *   1. KB header (name, description, ragflow status)
 *   2. KbUploader (drag-drop)
 *   3. Document list with per-row ingest status
 *      (pending → parsing → ready / failed), auto-refreshed via a
 *      polling loop while any row is still in-flight
 *   4. Chunk preview for the selected document (loads on demand via
 *      `/api/kb/{id}/documents/{doc_id}/chunks` — see ChunkPreview)
 *
 * We deliberately don't surface bot-mount here — that's part of the
 * bot edit dialog (BotFormDialog → "知识库" tab), which keeps the
 * "what bots use this KB" question co-located with the bot config.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, useToast } from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { KbUploader } from "@/components/KbUploader";
import { ChunkPreview } from "@/components/ChunkPreview";
import { api, KbChunk, KbDocument, KnowledgeBase } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  parsing: "解析中",
  ready: "就绪",
  failed: "失败",
};

const STATUS_COLOR: Record<string, { bg: string; fg: string }> = {
  pending: { bg: "rgba(148, 163, 184, 0.18)", fg: "#475569" },
  parsing: { bg: "rgba(250, 204, 21, 0.18)", fg: "#854D0E" },
  ready: { bg: "rgba(34, 197, 94, 0.18)", fg: "#166534" },
  failed: { bg: "rgba(239, 68, 68, 0.18)", fg: "#991B1B" },
};

export default function KnowledgeDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const kbId = params.id;
  const toast = useToast();
  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeDocId, setActiveDocId] = useState<number | null>(null);
  const [chunks, setChunks] = useState<KbChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!kbId) return;
    try {
      const [kbRow, docList] = await Promise.all([
        api.getKb(kbId),
        api.listKbDocuments(kbId),
      ]);
      setKb(kbRow);
      setDocs(docList);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "加载失败", description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [kbId, toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll every 2s while any doc is in-flight. Stops automatically
  // when everything is in a terminal state (ready / failed).
  useEffect(() => {
    if (!docs.some((d) => d.status === "pending" || d.status === "parsing")) {
      return;
    }
    const t = window.setInterval(() => {
      void (async () => {
        try {
          const docList = await api.listKbDocuments(kbId);
          setDocs(docList);
        } catch {
          // swallow — toast already raised on initial load failure
        }
      })();
    }, 2000);
    return () => window.clearInterval(t);
  }, [docs, kbId]);

  // Refresh the active chunk list whenever the user picks a different
  // doc, OR when the previously-picked doc's status flips to ready.
  useEffect(() => {
    if (activeDocId == null) {
      setChunks([]);
      return;
    }
    let cancelled = false;
    setChunksLoading(true);
    (async () => {
      try {
        // Backend exposes GET /api/kb/{kb_id}/documents/{doc_id}/chunks
        // for per-document chunk listing. The single-chunk endpoint
        // (/{kb_id}/chunks/{cid}) only carries one row, which isn't
        // enough for the preview list. Refresh whenever the doc's
        // status flips to ready (the worker just finished writing
        // chunks) by re-running this effect via deps.
        const rows = await api.listKbDocumentChunks(kbId, activeDocId);
        if (cancelled) return;
        setChunks(rows);
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          toast.push({
            title: "加载 chunk 失败",
            description: msg,
            variant: "error",
          });
        }
      } finally {
        if (!cancelled) setChunksLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeDocId, kbId, toast]);

  // Re-fetch the chunk list whenever the active doc's status flips to
  // ready — that's the moment the ingest worker stops writing new
  // chunks. Without this hook the preview would stay empty until the
  // user manually re-picks the doc.
  useEffect(() => {
    const doc = docs.find((d) => d.id === activeDocId);
    if (!doc || doc.status !== "ready") return;
    let cancelled = false;
    (async () => {
      try {
        const rows = await api.listKbDocumentChunks(kbId, doc.id);
        if (!cancelled) setChunks(rows);
      } catch {
        // The error toast has already fired in the primary effect;
        // swallow here to avoid double-toasting.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [docs, activeDocId, kbId]);

  const activeDoc = useMemo(
    () => docs.find((d) => d.id === activeDocId) ?? null,
    [docs, activeDocId],
  );

  const handleDeleteDoc = async (d: KbDocument) => {
    if (!confirm(`确认删除「${d.filename}」？所有 chunks 会一并删除。`)) return;
    try {
      await api.deleteKbDocument(kbId, d.id);
      toast.push({
        title: "已删除",
        description: `「${d.filename}」已移除`,
        variant: "success",
      });
      if (activeDocId === d.id) setActiveDocId(null);
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "删除失败", description: msg, variant: "error" });
    }
  };

  if (!kbId) {
    return (
      <PageShell>
        <div style={{ padding: 40 }}>无效的知识库 id</div>
      </PageShell>
    );
  }
  if (loading && !kb) {
    return (
      <PageShell>
        <div style={{ padding: 40, color: "var(--fg-subtle)" }}>加载中…</div>
      </PageShell>
    );
  }
  if (!kb) {
    return (
      <PageShell>
        <div style={{ padding: 40 }}>
          <h2 style={{ marginBottom: 8 }}>未找到知识库</h2>
          <Link
            href="/knowledge"
            style={{ color: "var(--accent)", textDecoration: "underline" }}
          >
            返回列表
          </Link>
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        <div style={{ marginBottom: 20 }}>
          <Link
            href="/knowledge"
            style={{
              fontSize: 12,
              color: "var(--fg-subtle)",
              textDecoration: "none",
            }}
          >
            ← 返回知识库列表
          </Link>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 16,
            marginBottom: 24,
          }}
        >
          <div style={{ fontSize: 32 }}>📚</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1
              style={{
                fontSize: 24,
                fontWeight: 700,
                letterSpacing: -0.3,
                marginBottom: 4,
              }}
            >
              {kb.name}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 13 }}>
              {kb.description || "（无描述）"}
            </p>
            <div
              style={{
                display: "flex",
                gap: 8,
                marginTop: 8,
                fontSize: 11,
                color: "var(--fg-subtle)",
              }}
            >
              {kb.is_public && (
                <span
                  style={{
                    padding: "2px 8px",
                    borderRadius: 999,
                    background: "rgba(34, 197, 94, 0.18)",
                    color: "#166534",
                  }}
                >
                  公开
                </span>
              )}
              <span>
                {docs.some((d) => d.status === "ready")
                  ? "本地检索就绪"
                  : "本地检索尚未就绪（等待首次上传）"}
              </span>
            </div>
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
            gap: 20,
            alignItems: "start",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <KbUploader kbId={kbId} onUploaded={refresh} />
            <div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  marginBottom: 8,
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                📄 文档 <span style={{ color: "var(--fg-subtle)" }}>{docs.length}</span>
              </div>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                {docs.length === 0 ? (
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
                    暂无文档，拖一个 PDF 试试
                  </div>
                ) : (
                  docs.map((d) => {
                    const status = STATUS_COLOR[d.status] ?? STATUS_COLOR.pending;
                    return (
                      <div
                        key={d.id}
                        onClick={() => setActiveDocId(d.id)}
                        style={{
                          padding: 10,
                          borderRadius: "var(--radius-sm)",
                          border:
                            activeDocId === d.id
                              ? "1px solid var(--accent)"
                              : "1px solid var(--border)",
                          background:
                            activeDocId === d.id
                              ? "rgba(167, 139, 250, 0.06)"
                              : "var(--surface-solid)",
                          cursor: "pointer",
                          transition: "all var(--transition)",
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                        }}
                      >
                        <span style={{ fontSize: 18 }}>📄</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div
                            style={{
                              fontSize: 13,
                              fontWeight: 500,
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                            title={d.filename}
                          >
                            {d.filename}
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--fg-subtle)",
                              marginTop: 2,
                              display: "flex",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            <span
                              style={{
                                padding: "1px 6px",
                                borderRadius: 999,
                                background: status.bg,
                                color: status.fg,
                                fontSize: 10,
                              }}
                            >
                              {STATUS_LABEL[d.status] ?? d.status}
                            </span>
                            {d.status === "ready" && (
                              <span>{d.chunk_count} chunks</span>
                            )}
                            {d.status === "failed" && d.error && (
                              <span
                                style={{ color: "var(--danger)", flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                                title={d.error}
                              >
                                {d.error}
                              </span>
                            )}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleDeleteDoc(d);
                          }}
                          style={{
                            border: "1px solid var(--border)",
                            background: "var(--surface-2)",
                            borderRadius: 6,
                            padding: "4px 8px",
                            fontSize: 11,
                            color: "var(--danger)",
                            cursor: "pointer",
                          }}
                        >
                          删除
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              🧩 Chunks
              {activeDoc && (
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--fg-subtle)",
                    fontWeight: 400,
                  }}
                >
                  {activeDoc.filename}
                </span>
              )}
            </div>
            {!activeDocId ? (
              <div
                style={{
                  padding: 18,
                  fontSize: 12,
                  color: "var(--fg-subtle)",
                  textAlign: "center",
                  border: "1px dashed var(--border)",
                  borderRadius: 8,
                }}
              >
                选一个文档查看 chunks
              </div>
            ) : chunksLoading ? (
              <div style={{ padding: 18, fontSize: 12, color: "var(--fg-subtle)" }}>
                加载中…
              </div>
            ) : (
              <ChunkPreview
                chunks={chunks}
                kbId={kbId}
                kbDocId={activeDocId}
                filename={activeDoc?.filename ?? ""}
              />
            )}
          </div>
        </div>

        <div style={{ marginTop: 32, fontSize: 12, color: "var(--fg-subtle)" }}>
          💡 提示：在「机器人」页编辑某个机器人 → 切到「📚 知识库」tab 即可把这个 KB 挂上去。
        </div>
      </div>
      {/* Stage 4 fix: shared PDF viewer across the page so any chunk
          preview opens the same drawer. */}
    </PageShell>
  );
}