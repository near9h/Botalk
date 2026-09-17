"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Avatar,
  avatarColor,
  Badge,
  Button,
  EmptyState,
  Input,
  useToast,
  vendorBadgeVariant,
} from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { api, ModelInfo, ModelTestResult, vendorLabel } from "@/lib/api";

/* ─── Per-model vendor icon ─── */

const VENDOR_ICON: Record<string, string> = {
  openai: "🟢",
  anthropic: "🟠",
  google: "🔵",
  zhipu: "🟣",
  alibaba: "🟧",
  deepseek: "🌊",
  bytedance: "🫐",
  moonshot: "🌙",
  baidu: "🔴",
  minimax: "🩷",
  other: "⚪",
};

function vendorIcon(v: string): string {
  return VENDOR_ICON[v] || VENDOR_ICON.other;
}

const VENDOR_FILTERS = [
  { value: "all", label: "全部" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "alibaba", label: "Alibaba" },
  { value: "minimax", label: "MiniMax" },
  { value: "other", label: "其他" },
];

type TestState =
  | { phase: "idle" }
  | { phase: "loading"; startedAt: number }
  | { phase: "done"; result: ModelTestResult; durationMs: number };

export default function ModelsPage() {
  const toast = useToast();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [vendor, setVendor] = useState("all");
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await api.listModels();
      setModels(r.data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "拉取模型失败", description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [refreshKey]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return models.filter((m) => {
      if (vendor !== "all" && m.vendor !== vendor) return false;
      if (q) {
        const blob = (m.id + " " + m.owned_by).toLowerCase();
        if (!blob.includes(q)) return false;
      }
      return true;
    });
  }, [models, query, vendor]);

  const grouped = useMemo(() => {
    const map = new Map<string, ModelInfo[]>();
    for (const m of filtered) {
      const list = map.get(m.vendor) ?? [];
      list.push(m);
      map.set(m.vendor, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  const test = async (m: ModelInfo) => {
    setTests((prev) => ({
      ...prev,
      [m.id]: { phase: "loading", startedAt: Date.now() },
    }));
    try {
      const r = await api.testModel({
        model: m.id,
        prompt: "用一句话介绍你自己（不超过 50 字）",
        temperature: 0.5,
      });
      const durationMs = Date.now() - (tests[m.id]?.phase === "loading" ? (tests[m.id] as { startedAt: number }).startedAt : Date.now());
      setTests((prev) => ({
        ...prev,
        [m.id]: { phase: "done", result: r, durationMs },
      }));
      if (r.ok) {
        toast.push({
          title: `${m.id} · 可用`,
          description: `延迟 ${r.latency_ms ?? "?"}ms · tokens ${r.total_tokens ?? "?"}`,
          variant: "success",
        });
      } else {
        toast.push({
          title: `${m.id} · 不可用`,
          description: r.error ?? "未知错误",
          variant: "error",
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setTests((prev) => ({
        ...prev,
        [m.id]: {
          phase: "done",
          result: { ok: false, model: m.id, reply: null, latency_ms: null, prompt_tokens: null, completion_tokens: null, total_tokens: null, error: msg },
          durationMs: 0,
        },
      }));
      toast.push({ title: `${m.id} · 请求失败`, description: msg, variant: "error" });
    }
  };

  const testAll = async () => {
    if (filtered.length === 0) return;
    if (!confirm(`将对 ${filtered.length} 个模型逐个发起测试请求（每个会消耗少量 token），确定继续？`)) return;
    for (const m of filtered) {
      // Sequential to avoid overwhelming the upstream gateway.
      // eslint-disable-next-line no-await-in-loop
      await test(m);
    }
  };

  const vendorCount = (v: string) =>
    v === "all" ? models.length : models.filter((m) => m.vendor === v).length;

  // Stats summary
  const tested = Object.values(tests).filter((t) => t.phase === "done");
  const passed = tested.filter((t) => t.phase === "done" && t.result.ok).length;
  const failed = tested.filter((t) => t.phase === "done" && !t.result.ok).length;

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: -0.5, marginBottom: 6 }}>
              模型管理
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {models.length > 0
                ? `从 NewAPI 拉取到 ${models.length} 个模型 · 已测试 ${tested.length}（通过 ${passed} / 失败 ${failed}）`
                : "正在从 NewAPI 拉取模型列表…"}
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="secondary" onClick={() => setRefreshKey((k) => k + 1)} disabled={loading}>
              🔄 刷新列表
            </Button>
            <Button onClick={testAll} disabled={loading || filtered.length === 0}>
              ⚡ 批量测试
            </Button>
          </div>
        </div>

        {/* Filter bar */}
        {models.length > 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 20,
              flexWrap: "wrap",
            }}
          >
            <div style={{ flex: "1 1 240px", maxWidth: 320 }}>
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="🔍 搜索模型 ID / owned_by…"
              />
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {VENDOR_FILTERS.map((v) => (
                <button
                  key={v.value}
                  onClick={() => setVendor(v.value)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 999,
                    fontSize: 12,
                    fontWeight: 500,
                    background: vendor === v.value ? "var(--accent)" : "var(--surface-2)",
                    color: vendor === v.value ? "white" : "var(--fg-muted)",
                    border: vendor === v.value ? "1px solid var(--accent)" : "1px solid var(--border)",
                    transition: "all var(--transition)",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  {v.value !== "all" && <span>{vendorIcon(v.value)}</span>}
                  {v.label}
                  <span
                    style={{
                      fontSize: 10,
                      opacity: 0.7,
                      fontFamily: '"JetBrains Mono", monospace',
                    }}
                  >
                    {vendorCount(v.value)}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Content */}
        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            正在从 NewAPI 拉取模型…
          </div>
        ) : models.length === 0 ? (
          <EmptyState
            emoji="🔌"
            title="无法从 NewAPI 拉取模型"
            description="检查后端的 NEWAPI_BASE_URL 和 NEWAPI_API_KEY 配置；也可以直接查看后端日志"
            action={
              <Button onClick={() => setRefreshKey((k) => k + 1)}>🔄 重试</Button>
            }
          />
        ) : filtered.length === 0 ? (
          <EmptyState emoji="🔍" title="没有匹配的模型" description="试试调整搜索词或切换过滤" />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            {grouped.map(([v, list]) => (
              <section key={v}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    marginBottom: 12,
                  }}
                >
                  <span style={{ fontSize: 20 }}>{vendorIcon(v)}</span>
                  <h2 style={{ fontSize: 16, fontWeight: 600 }}>{vendorLabel(v)}</h2>
                  <Badge variant={vendorBadgeVariant(v)}>{list.length}</Badge>
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
                    gap: 12,
                  }}
                >
                  {list.map((m) => (
                    <ModelCard key={m.id} model={m} state={tests[m.id]} onTest={() => test(m)} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </PageShell>
  );
}

/* ─── Single model card ─── */

function ModelCard({
  model,
  state,
  onTest,
}: {
  model: ModelInfo;
  state: TestState | undefined;
  onTest: () => void;
}) {
  const testing = state?.phase === "loading";
  const result = state?.phase === "done" ? state.result : null;

  const emoji = pickVendorEmoji(model.vendor, model.id);

  return (
    <div
      className="glass animate-fade-in"
      style={{
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <Avatar emoji={emoji} size={44} color={avatarColor(model.id)} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                fontFamily: '"JetBrains Mono", monospace',
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                maxWidth: "100%",
              }}
              title={model.id}
            >
              {model.id}
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <Badge variant={vendorBadgeVariant(model.vendor)}>{vendorLabel(model.vendor)}</Badge>
            {result?.ok === true && <Badge variant="success">✓ 可用</Badge>}
            {result?.ok === false && <Badge variant="warning">✗ 不可用</Badge>}
          </div>
        </div>
      </div>

      <div
        style={{
          fontSize: 11,
          color: "var(--fg-subtle)",
          fontFamily: '"JetBrains Mono", monospace',
        }}
      >
        owned_by: {model.owned_by}
      </div>

      {/* Result panel */}
      {result && (
        <div
          style={{
            padding: 10,
            borderRadius: "var(--radius-sm)",
            background: result.ok ? "rgba(134, 239, 172, 0.10)" : "var(--danger-bg)",
            border: `1px solid ${result.ok ? "rgba(134, 239, 172, 0.40)" : "#FCA5A5"}`,
            fontSize: 12,
            lineHeight: 1.55,
          }}
        >
          {result.ok ? (
            <>
              <div style={{ color: "var(--fg)", marginBottom: 6 }}>{result.reply}</div>
              <div style={{ display: "flex", gap: 8, fontSize: 11, color: "var(--fg-muted)" }}>
                <span>⏱ {result.latency_ms ?? "?"}ms</span>
                {result.total_tokens != null && (
                  <span>
                    📊 {result.total_tokens} tokens
                    {result.prompt_tokens != null && result.completion_tokens != null && (
                      <> ({result.prompt_tokens} + {result.completion_tokens})</>
                    )}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div style={{ color: "#991B1B", fontFamily: '"JetBrains Mono", monospace', fontSize: 11 }}>
              {result.error}
            </div>
          )}
        </div>
      )}

      <Button onClick={onTest} disabled={testing} size="md">
        {testing ? (
          <>
            <span style={{ animation: "spin 1s linear infinite", display: "inline-block" }}>⏳</span>
            测试中…
          </>
        ) : result ? (
          "🔁 重新测试"
        ) : (
          "⚡ 测试此模型"
        )}
      </Button>

      <style jsx>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

function pickVendorEmoji(vendor: string, modelId: string): string {
  const v = vendor.toLowerCase();
  if (v === "openai") return "🤖";
  if (v === "anthropic") return "🎭";
  if (v === "google") return "✨";
  if (v === "alibaba") return "🪶";
  if (v === "zhipu") return "🧠";
  if (v === "deepseek") return "🌊";
  if (v === "bytedance") return "🫐";
  if (v === "moonshot") return "🌙";
  if (v === "baidu") return "🔮";
  if (v === "minimax") return "🦄";
  // Fallback based on hash of model id
  const fallback = ["🧠", "✨", "💫", "🔮", "⚡", "🌟", "💎", "🚀", "🦾", "🎯"];
  let h = 0;
  for (let i = 0; i < modelId.length; i++) h = (h * 31 + modelId.charCodeAt(i)) | 0;
  return fallback[Math.abs(h) % fallback.length];
}