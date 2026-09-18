"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, EmptyState, useToast } from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { GroupCard } from "@/components/GroupCard";
import { GroupWizard } from "@/components/GroupWizard";
import { api, Bot, Group } from "@/lib/api";
import { BOT_TEMPLATES } from "@/lib/botTemplates";
import { useI18n } from "@/lib/i18n";

export default function HomePage() {
  const router = useRouter();
  const [groups, setGroups] = useState<Group[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const toast = useToast();
  const { t } = useI18n();

  const refresh = async () => {
    setLoading(true);
    try {
      const [g, b] = await Promise.all([api.listGroups(), api.listBots()]);
      setGroups(g);
      setBots(b);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("common.toast.loadFail"), description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const deleteGroup = async (publicId: string) => {
    try {
      await api.deleteGroup(publicId);
      toast.push({ title: t("common.toast.deleted"), variant: "success" });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("common.toast.deletedFail"), description: msg, variant: "error" });
    }
  };

  /**
   * One-click: ensure all 11 role-template bots exist, then create a group
   * "公司全员" with everyone in it and route the user into it.
   * - Skips bots whose name already exists.
   * - Continues on individual failures (e.g. invalid token for one vendor).
   */
  const seedFullTeam = async () => {
    if (bots.length === 0) {
      toast.push({
        title: t("groups.fullTeam.toast.noBots"),
        description: t("groups.fullTeam.toast.noBotsDesc"),
        variant: "error",
      });
      return;
    }
    setSeeding(true);
    try {
      const existing = new Set(bots.map((b) => b.name));
      let created = 0;
      for (const tpl of BOT_TEMPLATES) {
        if (existing.has(tpl.name)) continue;
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
          /* skip — surface in summary toast */
        }
      }

      // Re-fetch bots to include any newly created ones.
      const fresh = await api.listBots();
      setBots(fresh);
      const botIds = fresh.map((b) => b.id);

      const group = await api.createGroup({
        name: `公司全员讨论 · ${new Date().toLocaleString("zh-CN", { hour12: false })}`,
        description: `一键建群，包含全部 ${botIds.length} 位角色机器人`,
        mode: "auto",
        max_rounds: 3,
        bot_ids: botIds,
      });
      toast.push({
        title: t("groups.fullTeam.toast.success"),
        description: t("groups.fullTeam.toast.successDesc", { c: created, n: botIds.length }),
        variant: "success",
      });
      router.push(`/group/${group.public_id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("common.toast.createFail"), description: msg, variant: "error" });
    } finally {
      setSeeding(false);
    }
  };

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 28, gap: 12, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: -0.5, marginBottom: 6 }}>
              {t("groups.title")}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {groups.length > 0
                ? t("groups.subtitle_count_one", { n: groups.length, m: bots.length })
                : t("groups.subtitle_empty")}
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button
              variant="secondary"
              onClick={seedFullTeam}
              disabled={seeding || bots.length === 0}
              title={t("groups.fullTeam.hint")}
            >
              {seeding ? t("groups.fullTeam.creating") : t("groups.fullTeam")}
            </Button>
            <Button onClick={() => setWizardOpen(true)} size="lg">
              <span style={{ fontSize: 16, marginRight: 4 }}>＋</span> {t("groups.new")}
            </Button>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            {t("common.loading")}
          </div>
        ) : groups.length === 0 ? (
          <EmptyState
            emoji="💬"
            title={t("groups.empty.title")}
            description={
              bots.length === 0
                ? t("groups.empty.desc_no_bots")
                : t("groups.empty.desc")
            }
            action={
              <Button onClick={() => setWizardOpen(true)} size="lg">
                <span style={{ fontSize: 16, marginRight: 4 }}>＋</span> {t("groups.empty.cta")}
              </Button>
            }
          />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 16,
            }}
          >
            {groups.map((g) => (
              <GroupCard
                key={g.public_id}
                group={g}
                bots={bots}
                onDelete={() => deleteGroup(g.public_id)}
              />
            ))}
          </div>
        )}
      </div>

      <GroupWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        bots={bots}
        onCreated={() => refresh()}
      />
    </PageShell>
  );
}