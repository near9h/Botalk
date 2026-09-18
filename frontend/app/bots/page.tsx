"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, EmptyState, Input, Tabs, useToast } from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { BotCard } from "@/components/BotCard";
import { BotFormDialog } from "@/components/BotFormDialog";
import { api, Bot, User, vendorOfModelId } from "@/lib/api";
import { BOT_TEMPLATES } from "@/lib/botTemplates";

const VENDORS = [
  { value: "all", label: "全部", icon: "✦" },
  { value: "openai", label: "OpenAI", icon: "🟢" },
  { value: "anthropic", label: "Anthropic", icon: "🟠" },
  { value: "google", label: "Google", icon: "🔵" },
  { value: "alibaba", label: "Alibaba", icon: "🟧" },
  { value: "minimax", label: "MiniMax", icon: "🩷" },
  { value: "other", label: "其他", icon: "⚪" },
];

export default function BotsPage() {
  const toast = useToast();
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [vendor, setVendor] = useState("all");
  const [editing, setEditing] = useState<Bot | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [me, setMe] = useState<User | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [list, mine] = await Promise.all([
        api.listBots(),
        api.me().catch(() => null),
      ]);
      setBots(list);
      setMe(mine);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "加载机器人失败", description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return bots.filter((b) => {
      const v = vendorOfModelId(b.model);
      if (vendor !== "all" && v !== vendor) return false;
      if (q) {
        const blob = (b.name + " " + b.persona + " " + b.model).toLowerCase();
        if (!blob.includes(q)) return false;
      }
      return true;
    });
  }, [bots, query, vendor]);

  const deleteBot = async (b: Bot) => {
    try {
      await api.deleteBot(b.id);
      toast.push({ title: "已删除", description: `机器人「${b.name}」已移除`, variant: "success" });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // 403 = protected system bot. Surface a friendlier message that
      // matches the lock badge the user already sees on the card.
      const locked = /403|系统机器人|不可删除/.test(msg);
      toast.push({
        title: locked ? "系统机器人不可删除" : "删除失败",
        description: locked
          ? `「${b.name}」是系统机器人，由后端自动管理。`
          : msg,
        variant: "error",
      });
    }
  };

  /** One-click create all 11 role templates (skips any that already exist by name). */
  const seedTeam = async () => {
    if (
      !confirm(
        `将为「${BOT_TEMPLATES.length}」个角色模板创建机器人（已存在的同名机器人会被跳过）。继续？`,
      )
    )
      return;
    let created = 0;
    let skipped = 0;
    let failed = 0;
    const existingNames = new Set(bots.map((b) => b.name));
    for (const t of BOT_TEMPLATES) {
      if (existingNames.has(t.name)) {
        skipped++;
        continue;
      }
      try {
        await api.createBot({
          name: t.name,
          emoji: t.emoji,
          avatar_url: null,
          persona: t.persona,
          model: t.preferredModel ?? "gpt-4o",
          temperature: t.temperature,
          params: {},
        });
        created++;
      } catch {
        failed++;
      }
    }
    toast.push({
      title: "团队阵容创建完成",
      description: `新增 ${created} · 跳过 ${skipped} · 失败 ${failed}`,
      variant: failed > 0 ? "error" : "success",
    });
    await refresh();
  };

  const vendorCount = (v: string) =>
    v === "all" ? bots.length : bots.filter((b) => vendorOfModelId(b.model) === v).length;

  // System bots are always editable by everyone (they're meant to be
  // tweaked in this UI). Otherwise a bot is only writable by its owner
  // or an admin — public bots created by other users are read-only here.
  const canEdit = (b: Bot) => {
    if (b.is_system) return true;
    if (me?.role === "admin") return true;
    if (me && b.owner_id === me.id) return true;
    return false;
  };

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: -0.5, marginBottom: 6 }}>
              机器人管理
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {bots.length > 0
                ? `共 ${bots.length} 位机器人 · 点击卡片编辑人设与模型`
                : "为不同角色创建专门的 AI 助手"}
            </p>
          </div>
          <Button
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
            size="lg"
          >
            <span style={{ fontSize: 16, marginRight: 4 }}>＋</span> 新建机器人
          </Button>
          <Button
            variant="secondary"
            size="lg"
            onClick={seedTeam}
            title="一次性创建 11 个组织架构角色模板（已存在的同名机器人会跳过）"
          >
            🏢 一键创建团队
          </Button>
        </div>

        {/* Filter bar */}
        {bots.length > 0 && (
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
                placeholder="🔍 搜索名称 / 人设 / 模型…"
              />
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {VENDORS.map((v) => (
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
                  <span>{v.icon}</span>
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
            加载中…
          </div>
        ) : bots.length === 0 ? (
          <EmptyState
            emoji="🤖"
            title="还没有机器人"
            description="新建一位机器人，给它一个 emoji 头像、一个人设、选一个模型，就可以拉进群组讨论了"
            action={
              <Button
                onClick={() => {
                  setEditing(null);
                  setDialogOpen(true);
                }}
                size="lg"
              >
                ＋ 创建第一位机器人
              </Button>
            }
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            emoji="🔍"
            title="没有匹配的机器人"
            description="试试调整搜索词或切换过滤标签"
          />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
              gap: 14,
            }}
          >
            {filtered.map((b) => {
              const editable = canEdit(b);
              return (
                <BotCard
                  key={b.id}
                  bot={b}
                  onEdit={
                    editable
                      ? () => {
                          setEditing(b);
                          setDialogOpen(true);
                        }
                      : undefined
                  }
                  onDelete={editable ? () => deleteBot(b) : undefined}
                />
              );
            })}
          </div>
        )}
      </div>

      <BotFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        initial={editing}
        onSaved={refresh}
      />
    </PageShell>
  );
}