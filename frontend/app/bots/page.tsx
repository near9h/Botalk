"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, EmptyState, Input, Tabs, useToast } from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { BotCard } from "@/components/BotCard";
import { BotFormDialog } from "@/components/BotFormDialog";
import { api, Bot, User, vendorOfModelId } from "@/lib/api";
import { BOT_TEMPLATES } from "@/lib/botTemplates";
import { useI18n } from "@/lib/i18n";

const VENDOR_KEYS: Array<{ value: string; labelKey: string; icon: string }> = [
  { value: "all", labelKey: "bots.filter.all", icon: "✦" },
  { value: "openai", labelKey: "bots.filter.openai", icon: "🟢" },
  { value: "anthropic", labelKey: "bots.filter.anthropic", icon: "🟠" },
  { value: "google", labelKey: "bots.filter.google", icon: "🔵" },
  { value: "alibaba", labelKey: "bots.filter.alibaba", icon: "🟧" },
  { value: "minimax", labelKey: "bots.filter.minimax", icon: "🩷" },
  { value: "other", labelKey: "bots.filter.other", icon: "⚪" },
];

export default function BotsPage() {
  const toast = useToast();
  const { t } = useI18n();
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
      toast.push({ title: t("bots.toast.loadFail"), description: msg, variant: "error" });
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
      toast.push({ title: t("common.toast.deleted"), description: t("bots.toast.deletedFmt", { name: b.name }), variant: "success" });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // 403 = protected system bot. Surface a friendlier message that
      // matches the lock badge the user already sees on the card.
      const locked = /403|系统机器人|不可删除/.test(msg);
      toast.push({
        title: locked ? t("bots.toast.systemLocked") : t("common.toast.deletedFail"),
        description: locked
          ? t("bots.toast.systemLockedDescFmt", { name: b.name })
          : msg,
        variant: "error",
      });
    }
  };

  /** One-click create all 11 role templates (skips any that already exist by name). */
  const seedTeam = async () => {
    if (
      !confirm(
        t("bots.seedTeam.confirm", { n: BOT_TEMPLATES.length }),
      )
    )
      return;
    let created = 0;
    let skipped = 0;
    let failed = 0;
    const existingNames = new Set(bots.map((b) => b.name));
    for (const tpl of BOT_TEMPLATES) {
      if (existingNames.has(tpl.name)) {
        skipped++;
        continue;
      }
      try {
        await api.createBot({
          name: tpl.name,
          emoji: tpl.emoji,
          avatar_url: null,
          persona: tpl.persona,
          model: tpl.preferredModel ?? "gpt-4o",
          temperature: tpl.temperature,
          params: {},
        });
        created++;
      } catch {
        failed++;
      }
    }
    toast.push({
      title: t("bots.toast.teamCreated"),
      description: t("bots.toast.teamCreatedDesc", { c: created, s: skipped, f: failed }),
      variant: failed > 0 ? "error" : "success",
    });
    await refresh();
  };

  const vendorCount = (v: string) =>
    v === "all" ? bots.length : bots.filter((b) => vendorOfModelId(b.model) === v).length;

  // Authorization rule (mirrors backend/app/api/bots.py):
  //   - admin can edit everything (including system / protected bots)
  //   - protected bots: name + model locked, but persona / temperature /
  //     emoji / skills editable by anyone (admin + owner); non-admin
  //     non-owners still get 👁 只读
  //   - system bots: admin only — backend rejects everyone else with 403
  //   - non-protected non-system bots: owner (or admin) can edit
  //   - everyone else: 👁 只读
  const canEdit = (b: Bot) => {
    if (me?.role === "admin") return true;
    if (b.is_system) return false;
    if (me && b.owner_id === me.id) return true;
    return false;
  };

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: -0.5, marginBottom: 6 }}>
              {t("bots.title")}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {bots.length > 0
                ? t("bots.subtitle_with_count", { n: bots.length })
                : t("bots.subtitle_empty")}
            </p>
          </div>
          <Button
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
            size="lg"
          >
            <span style={{ fontSize: 16, marginRight: 4 }}>＋</span> {t("bots.action.new")}
          </Button>
          <Button
            variant="secondary"
            size="lg"
            onClick={seedTeam}
            title={t("bots.seedTeam.title")}
          >
            {t("bots.action.seedTeam")}
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
                placeholder={t("bots.search.placeholder")}
              />
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {VENDOR_KEYS.map((v) => (
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
                  {t(v.labelKey)}
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
            {t("common.loading")}
          </div>
        ) : bots.length === 0 ? (
          <EmptyState
            emoji="🤖"
            title={t("bots.empty.title")}
            description={t("bots.empty.desc")}
            action={
              <Button
                onClick={() => {
                  setEditing(null);
                  setDialogOpen(true);
                }}
                size="lg"
              >
                {t("bots.empty.cta")}
              </Button>
            }
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            emoji="🔍"
            title={t("bots.noMatch.title")}
            description={t("bots.noMatch.desc")}
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