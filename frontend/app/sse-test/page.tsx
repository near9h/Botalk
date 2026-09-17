"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Minimal SSE diagnostic page — bypasses GroupPage / Composer / ChatBubble
 * entirely. Posts directly to `/api/chat/stream`, renders raw SSE frames
 * one-by-one so we can see EXACTLY when each event reaches the browser.
 *
 * Use this to tell apart:
 *   - backend buffering (all events arrive in one chunk at the very end)
 *   - nginx buffering (same symptom, but headers confirm the upstream is OK)
 *   - frontend parsing bug (events arrive progressively but `onEvent` doesn't
 *     update state)
 *
 * Each row shows: (1) ms since page load, (2) the raw `event:` line,
 * (3) the raw `data:` line, (4) whether the chunk boundary coincided with
 * the event boundary.
 */
export default function SseTestPage() {
  const [groupId, setGroupId] = useState("5");
  const [prompt, setPrompt] = useState("ping");
  const [running, setRunning] = useState(false);
  const [rows, setRows] = useState<
    { t: number; event: string; data: string; sizeBytes: number; chunkIndex: number }[]
  >([]);
  const [rawLog, setRawLog] = useState<string[]>([]);
  const startRef = useRef<number>(0);
  const chunkIdxRef = useRef(0);

  const run = async () => {
    setRows([]);
    setRawLog([]);
    setRunning(true);
    startRef.current = performance.now();
    chunkIdxRef.current = 0;

    // Direct same-origin POST so we exercise the SAME nginx path the
    // GroupPage uses — if this streams, the GroupPage should too.
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ group_id: Number(groupId), prompt }),
    });

    const hdrs: string[] = [];
    res.headers.forEach((v, k) => hdrs.push(`${k}: ${v}`));
    setRawLog((l) => [`--- response headers ---`, ...hdrs, "--- end headers ---"]);

    if (!res.body) {
      setRawLog((l) => [...l, "ERROR: no response body"]);
      setRunning(false);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let chunkIndex = 0;

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        chunkIndex += 1;
        const chunkText = decoder.decode(value, { stream: true });
        const t = Math.round(performance.now() - startRef.current);
        setRawLog((l) => [
          ...l,
          `[+${t}ms] CHUNK#${chunkIndex} (${value.byteLength}B): ${JSON.stringify(chunkText)}`,
        ]);
        buffer += chunkText;
        // sse_starlette emits CRLF ("\r\n\r\n") between events; normalize so
        // the "\n\n" split below matches on both CRLF and LF servers.
        buffer = buffer.replace(/\r\n/g, "\n");
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const lines = raw.split("\n");
          let event = "message";
          let data = "";
          for (const line of lines) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          const ms = Math.round(performance.now() - startRef.current);
          setRows((r) => [
            ...r,
            { t: ms, event, data, sizeBytes: raw.length, chunkIndex },
          ]);
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setRawLog((l) => [...l, `ERROR during read: ${msg}`]);
    }
    setRunning(false);
  };

  useEffect(() => {
    // auto-run once so you don't have to click
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ padding: 24, fontFamily: "ui-monospace, monospace", fontSize: 12 }}>
      <h1 style={{ fontSize: 18, marginBottom: 12 }}>SSE Diagnostic Page</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
        <label>
          group_id:&nbsp;
          <input
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
            style={{ width: 60, padding: 4 }}
          />
        </label>
        <label>
          prompt:&nbsp;
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            style={{ width: 240, padding: 4 }}
          />
        </label>
        <button onClick={run} disabled={running} style={{ padding: "4px 12px" }}>
          {running ? "running…" : "run"}
        </button>
        <span style={{ color: "#666" }}>
          {rows.length} events · {rawLog.length} log lines
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <h2 style={{ fontSize: 14 }}>Parsed events</h2>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr style={{ background: "#f4f4f4" }}>
                <th style={th}>+ms</th>
                <th style={th}>chunk#</th>
                <th style={th}>event</th>
                <th style={th}>data preview</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #eee" }}>
                  <td style={td}>{r.t}</td>
                  <td style={td}>#{r.chunkIndex}</td>
                  <td style={{ ...td, color: r.event === "token" ? "#0a0" : "#00a" }}>
                    {r.event}
                  </td>
                  <td style={{ ...td, maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {r.data.slice(0, 120)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h2 style={{ fontSize: 14 }}>Raw chunks &amp; headers</h2>
          <pre
            style={{
              background: "#111",
              color: "#0f0",
              padding: 12,
              borderRadius: 6,
              maxHeight: 600,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {rawLog.join("\n")}
          </pre>
        </div>
      </div>
    </div>
  );
}

const th: React.CSSProperties = {
  padding: "4px 8px",
  textAlign: "left",
  borderBottom: "1px solid #ccc",
  fontWeight: 600,
};
const td: React.CSSProperties = {
  padding: "4px 8px",
  verticalAlign: "top",
};