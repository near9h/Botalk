"use client";

/**
 * 气泡底部的来源清单。
 *
 * 只列**正文真正引用到**的 chunk —— `cited_refs` 是「本次检索命中并注入
 * 提示词的候选 chunk」，LLM 只给自己用到的那些标 `[N]`，直接全量渲染会
 * 出现「正文 4 个角标、底下 5 条来源」。解析交给 `resolveCitedChunks`，
 * 编号直接取角标数字，与正文严格一致；一条都没引用就不渲染这条 footer。
 *
 * 正文里内联的角标由 markdown.ts 的 `citation` class 渲染，点击角标和点
 * 击这里的条目都走同一个 onOpen 回调。
 */
import { useMemo } from "react";
import type { CitedRef } from "@/lib/api";
import { resolveCitedChunks } from "@/lib/markdown";

export function CitedRefsFooter({
  refs,
  content,
  onOpen,
}: {
  /** 该条消息的 `cited_refs`（检索候选集，用于把角标解析回 chunk）。 */
  refs: CitedRef[];
  /** 该条消息的正文原文，用来解析正文里的 `[N]` / `[doc: …]` 标记。 */
  content: string;
  onOpen: (ref: CitedRef) => void;
}) {
  const cited = useMemo(
    () => resolveCitedChunks(content, refs),
    [content, refs],
  );
  if (cited.length === 0) return null;
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
        {cited.map(({ ref, ordinal }) => (
          <span
            key={ref.chunk_id}
            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
          >
            <button
              type="button"
              onClick={() => onOpen(ref)}
              title={ref.snippet || ref.filename}
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
              [{ordinal}]
            </button>
            <span
              style={{
                maxWidth: 220,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={ref.citation_key || ref.filename}
            >
              {(ref.citation_key || ref.filename || "未知来源").replace(/\.pdf$/i, "")}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
