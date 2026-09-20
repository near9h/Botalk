"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  EmptyState,
  IconButton,
  Input,
  Label,
  Select,
  Textarea,
  useToast,
} from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { api, Skill, SkillAsset } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const TYPE_LABEL_KEY: Record<string, string> = {
  knowledge: "skillType.knowledge",
  tool: "skillType.tool",
  mcp: "skillType.mcp",
};

const CATEGORY_LABEL_KEY: Record<string, string> = {
  document: "skillCategory.document",
  search: "skillCategory.search",
  crawl: "skillCategory.crawl",
  chart: "skillCategory.chart",
  mcp: "skillCategory.mcp",
  custom: "skillCategory.custom",
};

export default function SkillsPage() {
  const toast = useToast();
  const { t } = useI18n();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);

  // Import form state
  const [mdUrl, setMdUrl] = useState("");
  const [mdUrlName, setMdUrlName] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpName, setMcpName] = useState("");
  const [mcpTransport, setMcpTransport] = useState("streamable-http");
  const [communityQ, setCommunityQ] = useState("");
  const [communityResults, setCommunityResults] = useState<Array<Record<string, unknown>>>([]);
  const [installingUrl, setInstallingUrl] = useState<string | null>(null);
  // Independent modal so the marketplace results feel like a real
  // "app store" rather than a flat list under the search box.
  const [communityOpen, setCommunityOpen] = useState(false);
  const [importing, setImporting] = useState(false);

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [cName, setCName] = useState("");
  const [cDesc, setCDesc] = useState("");
  const [cInstructions, setCInstructions] = useState("");

  // Template asset upload
  const [assetTarget, setAssetTarget] = useState<Skill | null>(null);
  // Manage-templates dialog (per skill). The dialog reads the latest skill
  // from the `skills` list by id so it always shows fresh data after
  // uploads / patches / deletes triggered inside it.
  const [templatesTarget, setTemplatesTarget] = useState<Skill | null>(null);
  // Inline editor for a single asset (rename + description) so we don't
  // fall back to window.prompt — looks like the rest of the UI.
  const [editingAsset, setEditingAsset] = useState<SkillAsset | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const mdFileRef = useRef<HTMLInputElement>(null);
  const assetFileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setSkills(await api.listSkills());
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("skills.toast.loadFail"), description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const pushErr = (titleKey: string, e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    toast.push({ title: t(titleKey), description: msg, variant: "error" });
  };

  const onImportSkillMdFile = async (file: File | undefined) => {
    if (!file) return;
    setImporting(true);
    try {
      const s = await api.importSkillMdFile(file);
      toast.push({ title: t("common.toast.created"), description: t("skills.toast.importedFmt", { name: s.name }), variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("skills.toast.importFail", e);
    } finally {
      setImporting(false);
      if (mdFileRef.current) mdFileRef.current.value = "";
    }
  };

  const onImportMdUrl = async () => {
    if (!mdUrl.trim()) return;
    setImporting(true);
    try {
      const s = await api.importSkillMdUrl(mdUrl.trim(), mdUrlName.trim() || undefined);
      toast.push({ title: t("common.toast.created"), description: t("skills.toast.importedFmt", { name: s.name }), variant: "success" });
      setMdUrl("");
      setMdUrlName("");
      await refresh();
    } catch (e) {
      pushErr("skills.toast.importFail", e);
    } finally {
      setImporting(false);
    }
  };

  const onImportMcp = async () => {
    if (!mcpUrl.trim()) return;
    setImporting(true);
    try {
      const s = await api.importMcp({
        url: mcpUrl.trim(),
        transport: mcpTransport,
        name: mcpName.trim() || undefined,
      });
      toast.push({ title: t("common.toast.created"), description: t("skills.toast.importedMcpFmt", { name: s.name }), variant: "success" });
      setMcpUrl("");
      setMcpName("");
      await refresh();
    } catch (e) {
      pushErr("skills.toast.mcpImportFail", e);
    } finally {
      setImporting(false);
    }
  };

  const onCommunitySearch = async () => {
    if (!communityQ.trim()) return;
    setImporting(true);
    try {
      const results = await api.communitySearch(communityQ.trim());
      setCommunityResults(results);
      setCommunityOpen(true); // pop the marketplace modal
    } catch (e) {
      pushErr("skills.toast.searchFail", e);
      setCommunityResults([]);
    } finally {
      setImporting(false);
    }
  };

  // Build a stable key per card so double-clicks don't fire two installs.
  const onInstallCommunity = async (item: Record<string, unknown>) => {
    const url = String(item.url ?? "");
    if (!url) return;
    setInstallingUrl(url);
    try {
      const installed = await api.installCommunity({
        url,
        transport: String(item.transport ?? "streamable-http"),
        name: item.title ? String(item.title) : undefined,
        description: item.description ? String(item.description) : undefined,
        source: item.source ? String(item.source) : undefined,
      });
      toast.push({
        title: t("skills.toast.installedFmt"),
        description: t("skills.toast.installedDescFmt", { name: installed.name }),
        variant: "success",
      });
      // Mark this row as installed so the user sees a checkmark.
      setCommunityResults((prev) =>
        prev.map((r) => (r === item ? { ...r, __installed: installed.id } : r)),
      );
      await refresh();
    } catch (e) {
      pushErr("skills.toast.installFail", e);
    } finally {
      setInstallingUrl(null);
    }
  };

  // Channel badge styling. Color-coded so the three sources are easy to
  // tell apart in a long list. Labels looked up via the dict at render time.
  type SourceStyle = { labelKey: string; bg: string; fg: string };
  const SOURCE_STYLE: Record<string, SourceStyle> = {
    mcp_marketplace: { labelKey: "skillSource.mcp_marketplace", bg: "rgba(99,102,241,0.15)", fg: "#4338ca" },
    anthropic: { labelKey: "skillSource.anthropic", bg: "rgba(234,88,12,0.15)", fg: "#9a3412" },
    findskill: { labelKey: "skillSource.findskill", bg: "rgba(14,165,233,0.15)", fg: "#0369a1" },
  };

  // Render a result card for the marketplace dialog.
  const renderCommunityCard = (r: Record<string, unknown>, i: number) => {
    const title = String(r.title ?? r.name ?? r.id ?? t("skills.community.unknownLabel", { n: i + 1 }));
    const url = String(r.url ?? r.html_url ?? r.homepage ?? "");
    const desc = String(r.description ?? "");
    const transport = String(r.transport ?? "streamable-http");
    const installable = Boolean(r.installable ?? !!url);
    const remoteUrl = (r.remote_url as string | undefined) ?? "";
    const githubUrl = (r.github_url as string | undefined) ?? "";
    const installedId = (r.__installed as number | undefined) ?? null;
    const busy = installingUrl === url;
    const source = String(r.source ?? "");
    const sourceMeta = SOURCE_STYLE[source] ?? { labelKey: "", bg: "var(--surface-solid)", fg: "var(--fg-muted)" };
    const sourceLabel = sourceMeta.labelKey ? t(sourceMeta.labelKey) : (source || t("skills.community.unknownSource"));
    const scoreVal = typeof r.score === "number" ? r.score : null;
    const downloadsVal = typeof r.downloads === "number" ? r.downloads : null;
    const alsoIn = Array.isArray(r.also_in) ? (r.also_in as string[]) : [];

    return (
      <div
        key={`${title}-${i}`}
        style={{
          padding: "12px 14px",
          borderRadius: "var(--radius-sm)",
          background: "var(--surface-2)",
          border: installedId
            ? "1px solid rgba(34, 197, 94, 0.45)"
            : "1px solid var(--border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{title}</span>
            {/* 渠道标签 */}
            <span
              style={{
                fontSize: 10,
                padding: "2px 8px",
                borderRadius: 999,
                background: sourceMeta.bg,
                color: sourceMeta.fg,
                fontWeight: 600,
              }}
              title={sourceLabel}
            >
              {sourceLabel}
            </span>
            {/* 评分 */}
            {scoreVal !== null && (
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 6px",
                  borderRadius: 999,
                  background: "var(--surface-solid)",
                  border: "1px solid var(--border)",
                  color: "var(--fg-muted)",
                }}
                title={t("skills.community.scoreTitle")}
              >
                ★ {scoreVal >= 1000 ? `${(scoreVal / 1000).toFixed(1)}k` : scoreVal.toFixed(1)}
              </span>
            )}
            {/* 下载量 */}
            {downloadsVal !== null && (
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 6px",
                  borderRadius: 999,
                  background: "var(--surface-solid)",
                  border: "1px solid var(--border)",
                  color: "var(--fg-muted)",
                }}
                title={t("skills.community.downloadsTitle")}
              >
                ⬇ {downloadsVal >= 1000 ? `${(downloadsVal / 1000).toFixed(1)}k` : downloadsVal}
              </span>
            )}
            {transport && (
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 6px",
                  borderRadius: 999,
                  background: "var(--surface-solid)",
                  border: "1px solid var(--border)",
                  color: "var(--fg-subtle)",
                }}
              >
                {transport}
              </span>
            )}
            {installedId ? (
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 8px",
                  borderRadius: 999,
                  background: "rgba(34, 197, 94, 0.15)",
                  color: "#15803d",
                  fontWeight: 600,
                }}
              >
                {t("skills.community.installedBadge")}
              </span>
            ) : !installable ? (
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 8px",
                  borderRadius: 999,
                  background: "var(--surface-solid)",
                  border: "1px solid var(--border)",
                  color: "var(--fg-subtle)",
                }}
              >
                {t("skills.community.needLocal")}
              </span>
            ) : null}
            {alsoIn.length > 0 && (
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 8px",
                  borderRadius: 999,
                  background: "rgba(168,85,247,0.12)",
                  color: "#7e22ce",
                }}
                title={t("skills.community.alsoInTitleFmt", { list: alsoIn.join(", ") })}
              >
                {t("skills.community.alsoInFmt", { list: alsoIn.map((s) => SOURCE_STYLE[s]?.labelKey ? t(SOURCE_STYLE[s]!.labelKey) : s).join(", ") })}
              </span>
            )}
          </div>
          {desc && (
            <div
              style={{
                fontSize: 12,
                color: "var(--fg-muted)",
                lineHeight: 1.5,
                marginTop: 4,
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              {desc}
            </div>
          )}
          {(remoteUrl || githubUrl) && (
            <div style={{ display: "flex", gap: 10, marginTop: 6, flexWrap: "wrap" }}>
              {remoteUrl && (
                <span style={{ fontSize: 11, color: "var(--accent)", wordBreak: "break-all" }}>
                  ⇨ {remoteUrl}
                </span>
              )}
              {githubUrl && (
                <a
                  href={githubUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  style={{ fontSize: 11, color: "var(--fg-muted)" }}
                >
                  GitHub ↗
                </a>
              )}
            </div>
          )}
        </div>
        {installable && url && !installedId && (
          <Button size="sm" onClick={() => onInstallCommunity(r)} disabled={busy}>
            {busy ? t("skills.community.installing") : t("skills.community.install")}
          </Button>
        )}
      </div>
    );
  };

  // 健康监控：把 `__health__` 错误拆出来作为顶部警告条
  const healthEntry = communityResults.find((r) => r.__health__) as
    | { errors: Record<string, string> }
    | undefined;
  const healthErrors = healthEntry?.errors ?? {};
  const displayResults = communityResults.filter((r) => !r.__health__);

  const onCreateSkill = async () => {
    if (!cName.trim()) {
      toast.push({ title: t("skills.toast.empty.name"), variant: "error" });
      return;
    }
    try {
      const s = await api.createSkill({
        key: "",
        name: cName.trim(),
        description: cDesc.trim(),
        type: "knowledge",
        category: "custom",
        icon: "📄",
        manifest: { instructions: cInstructions.trim(), assets: [] },
        config_schema: {
          assets: { type: "list", label: t("skills.create.assets.label"), accept: [".md", ".markdown", ".txt"] },
        },
      });
      toast.push({ title: t("common.toast.created"), description: t("skills.toast.importedFmt", { name: s.name }), variant: "success" });
      setCreateOpen(false);
      setCName("");
      setCDesc("");
      setCInstructions("");
      await refresh();
    } catch (e) {
      pushErr("skills.toast.createFail", e);
    }
  };

  const onUploadAsset = async (file: File | undefined) => {
    if (!file || !assetTarget) return;
    try {
      const s = await api.uploadSkillAsset(assetTarget.id, file);
      toast.push({ title: t("skills.toast.uploaded.title"), description: t("skills.toast.uploadedFmt", { name: s.name }), variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("skills.toast.uploadFail", e);
    } finally {
      setAssetTarget(null);
      if (assetFileRef.current) assetFileRef.current.value = "";
    }
  };

  const onSetDefaultAsset = async (s: Skill, a: SkillAsset) => {
    try {
      await api.updateSkillAsset(s.id, a.id, { is_default: true });
      toast.push({ title: t("skills.toast.defaultSet.title"), description: t("skills.toast.defaultSetFmt", { name: a.name }), variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("skills.toast.defaultFail", e);
    }
  };

  const openEditAsset = (a: SkillAsset) => {
    setEditingAsset(a);
    setEditName(a.name);
    setEditDesc(a.description || "");
  };
  const closeEditAsset = () => {
    setEditingAsset(null);
    setEditName("");
    setEditDesc("");
  };
  const onSaveEditAsset = async (s: Skill) => {
    if (!editingAsset) return;
    const trimmedName = editName.trim();
    if (!trimmedName) {
      toast.push({ title: t("skills.toast.empty.templateName"), variant: "error" });
      return;
    }
    try {
      await api.updateSkillAsset(s.id, editingAsset.id, {
        name: trimmedName,
        description: editDesc.trim(),
      });
      toast.push({ title: t("skills.toast.assetSaved.title"), description: t("skills.toast.assetSavedFmt", { name: trimmedName }), variant: "success" });
      await refresh();
      closeEditAsset();
    } catch (e) {
      pushErr("skills.toast.assetFail", e);
    }
  };

  const onDeleteAsset = async (s: Skill, a: SkillAsset) => {
    if (!confirm(t("skills.manage.assetDeleteConfirmFmt", { name: a.name }))) return;
    try {
      await api.deleteSkillAsset(s.id, a.id);
      toast.push({ title: t("skills.toast.deleted.title"), description: t("skills.toast.deletedFmt", { name: a.name }), variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("skills.toast.assetDeleteFail", e);
    }
  };

  const onDelete = async (s: Skill) => {
    if (!confirm(t("skills.deleteConfirmFmt", { name: s.name }))) return;
    try {
      await api.deleteSkill(s.id);
      toast.push({ title: t("common.toast.deleted"), description: t("skills.toast.skillDeletedFmt", { name: s.name }), variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("skills.toast.skillDeleteFail", e);
    }
  };

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            marginBottom: 24,
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: -0.5, marginBottom: 6 }}>
              {t("skills.title")}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {t("skills.subtitle")}
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button
              variant="secondary"
              size="lg"
              disabled={importing}
              onClick={() => mdFileRef.current?.click()}
            >
              {t("skills.action.importMd")}
            </Button>
            <Button size="lg" onClick={() => setCreateOpen(true)}>
              {t("skills.action.createKb")}
            </Button>
          </div>
        </div>

        {/* Import panel */}
        <Card style={{ marginBottom: 24, padding: 20 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
            <div>
              <Label>{t("skills.section.mdImport")}</Label>
              <div style={{ display: "flex", gap: 6 }}>
                <Input
                  value={mdUrl}
                  onChange={(e) => setMdUrl(e.target.value)}
                  placeholder="https://…/SKILL.md"
                />
                <Input
                  value={mdUrlName}
                  onChange={(e) => setMdUrlName(e.target.value)}
                  placeholder={t("skills.section.mdImport.name")}
                  style={{ maxWidth: 120 }}
                />
                <Button variant="secondary" onClick={onImportMdUrl} disabled={importing || !mdUrl.trim()}>
                  {t("skills.btn.import")}
                </Button>
              </div>
            </div>

            <div>
              <Label>{t("skills.section.mcpConnect")}</Label>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <Input
                  value={mcpUrl}
                  onChange={(e) => setMcpUrl(e.target.value)}
                  placeholder="http://host/mcp"
                />
                <Input
                  value={mcpName}
                  onChange={(e) => setMcpName(e.target.value)}
                  placeholder={t("skills.section.mcpConnect.name")}
                  style={{ maxWidth: 120 }}
                />
                <Button variant="secondary" onClick={onImportMcp} disabled={importing || !mcpUrl.trim()}>
                  {t("skills.btn.connect")}
                </Button>
              </div>
            </div>

            <div>
              <Label>{t("skills.section.community")}</Label>
              <div style={{ display: "flex", gap: 6 }}>
                <Input
                  value={communityQ}
                  onChange={(e) => setCommunityQ(e.target.value)}
                  placeholder={t("skills.search.placeholder")}
                />
                <Button variant="secondary" onClick={onCommunitySearch} disabled={importing || !communityQ.trim()}>
                  {t("skills.btn.search")}
                </Button>
              </div>
            </div>
          </div>
        </Card>

        {/* Skill grid */}
        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            {t("common.loading")}
          </div>
        ) : skills.length === 0 ? (
          <EmptyState
            emoji="🧩"
            title={t("skills.empty.title")}
            description={t("skills.empty.desc")}
          />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 14,
            }}
          >
            {skills.map((s) => (
              <Card key={s.id} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ fontSize: 28 }}>{s.icon || "🧩"}</div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{s.name}</div>
                    <div style={{ fontSize: 11, color: "var(--fg-subtle)" }}>{s.key}</div>
                  </div>
                  {s.builtin && <Badge variant="info">{t("skills.badge.builtin")}</Badge>}
                </div>
                <p style={{ fontSize: 13, color: "var(--fg-muted)", lineHeight: 1.55, margin: 0, flex: 1 }}>
                  {s.description || t("skills.noDescription")}
                </p>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Badge variant="auto">{TYPE_LABEL_KEY[s.type] ? t(TYPE_LABEL_KEY[s.type]) : s.type}</Badge>
                  <Badge variant="default">{CATEGORY_LABEL_KEY[s.category] ? t(CATEGORY_LABEL_KEY[s.category]) : s.category}</Badge>
                  <Badge variant="default">{t("skills.assetCountFmt", { n: s.bot_count ?? 0 })}</Badge>
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                  {s.type === "knowledge" && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setAssetTarget(s);
                        assetFileRef.current?.click();
                      }}
                      style={{ flex: 1 }}
                    >
                      {t("skills.action.uploadTemplate")}
                    </Button>
                  )}
                  {s.type === "knowledge" && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setTemplatesTarget(s)}
                    >
                      {t("skills.action.manageTemplatesFmt", { n: ((s.manifest?.assets as SkillAsset[]) || []).length })}
                    </Button>
                  )}
                  {!s.builtin && (
                    <Button variant="danger" size="sm" onClick={() => onDelete(s)}>
                      {t("skills.action.delete")}
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}

        {/* Hidden file inputs */}
        <input
          ref={mdFileRef}
          type="file"
          accept=".md,.txt"
          style={{ display: "none" }}
          onChange={(e) => onImportSkillMdFile(e.target.files?.[0])}
        />
        <input
          ref={assetFileRef}
          type="file"
          accept=".md,.markdown,.txt"
          style={{ display: "none" }}
          onChange={(e) => onUploadAsset(e.target.files?.[0])}
        />
      </div>

      {/* Create knowledge skill dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader
            title={t("skills.create.dialogTitle")}
            description={t("skills.create.dialogDesc")}
            onClose={() => setCreateOpen(false)}
          />
          <div style={{ display: "grid", gap: 16, marginTop: 20 }}>
            <div>
              <Label>{t("skills.create.label.name")}</Label>
              <Input value={cName} onChange={(e) => setCName(e.target.value)} placeholder={t("skills.create.name.placeholder")} />
            </div>
            <div>
              <Label>{t("skills.create.label.desc")}</Label>
              <Input value={cDesc} onChange={(e) => setCDesc(e.target.value)} placeholder={t("skills.create.desc.placeholder")} />
            </div>
            <div>
              <Label>{t("skills.create.label.instructions")}</Label>
              <Textarea
                rows={6}
                value={cInstructions}
                onChange={(e) => setCInstructions(e.target.value)}
                placeholder={t("skills.create.instructions.placeholder")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={onCreateSkill}>{t("kb.form.create")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ───── Manage-templates dialog ───── */}
      <Dialog open={!!templatesTarget} onOpenChange={(v) => !v && setTemplatesTarget(null)}>
        <DialogContent>
          {templatesTarget && (() => {
              // Always read the latest copy of this skill so the list
              // updates immediately after we PATCH/POST/DELETE.
              const latest = skills.find((x) => x.id === templatesTarget.id) || templatesTarget;
              const assets = (latest.manifest?.assets as SkillAsset[]) || [];
              return (
                <>
                  <DialogHeader
                    title={t("skills.manage.titleFmt", { name: latest.name })}
                    description={t("skills.manage.descFmt", { name: latest.name })}
                    onClose={() => setTemplatesTarget(null)}
                  />
                  <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 20 }}>
                    {assets.length === 0 ? (
                      <div
                        style={{
                          padding: "32px 20px",
                          textAlign: "center",
                          borderRadius: "var(--radius)",
                          border: "1px dashed var(--border-strong)",
                          color: "var(--fg-muted)",
                          fontSize: 13,
                        }}
                      >
                        {t("skills.manage.noAssets")}
                      </div>
                    ) : (
                      assets.map((a, idx) => (
                        <div
                          key={a.id}
                          className="glass"
                          style={{
                            padding: 14,
                            borderRadius: "var(--radius)",
                            display: "flex",
                            alignItems: "flex-start",
                            gap: 12,
                          }}
                        >
                          <div
                            style={{
                              width: 32,
                              height: 32,
                              borderRadius: 8,
                              background: "linear-gradient(135deg, var(--accent), var(--accent-2))",
                              color: "white",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: 13,
                              fontWeight: 600,
                              flexShrink: 0,
                            }}
                          >
                            {idx + 1}
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                                marginBottom: 4,
                                flexWrap: "wrap",
                              }}
                            >
                              <span
                                style={{
                                  fontWeight: 600,
                                  fontSize: 14,
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                  flex: 1,
                                  minWidth: 0,
                                }}
                                title={a.name}
                              >
                                {a.name}
                              </span>
                              {a.is_default ? (
                                <Badge variant="info">{t("skills.manage.defaultBadge")}</Badge>
                              ) : (
                                <button
                                  onClick={() => onSetDefaultAsset(latest, a)}
                                  style={{
                                    fontSize: 11,
                                    padding: "2px 8px",
                                    borderRadius: 999,
                                    background: "transparent",
                                    color: "var(--fg-muted)",
                                    border: "1px solid var(--border)",
                                    cursor: "pointer",
                                  }}
                                  title={t("skills.manage.setDefaultTitle")}
                                >
                                  {t("skills.manage.setDefault")}
                                </button>
                              )}
                            </div>
                            <div
                              style={{
                                fontSize: 12,
                                color: "var(--fg-muted)",
                                lineHeight: 1.5,
                                marginBottom: 8,
                              }}
                            >
                              {a.description || (
                                <span style={{ color: "var(--fg-subtle)" }}>{t("skills.manage.noDescPlaceholder")}</span>
                              )}
                            </div>
                            <div style={{ display: "flex", gap: 6 }}>
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => openEditAsset(a)}
                              >
                                {t("skills.manage.edit")}
                              </Button>
                              <Button
                                size="sm"
                                variant="danger"
                                onClick={() => onDeleteAsset(latest, a)}
                              >
                                {t("skills.manage.delete")}
                              </Button>
                            </div>
                          </div>
                        </div>
                      ))
                    )}

                    <div
                      style={{
                        display: "flex",
                        gap: 8,
                        paddingTop: 4,
                      }}
                    >
                      <Button
                        variant="primary"
                        size="md"
                        onClick={() => {
                          setTemplatesTarget(null);
                          setAssetTarget(latest);
                          assetFileRef.current?.click();
                        }}
                        style={{ flex: 1 }}
                      >
                        {t("skills.manage.uploadNew")}
                      </Button>
                    </div>
                  </div>
                </>
              );
            })()}
        </DialogContent>
      </Dialog>

      {/* ───── Edit-asset dialog (rename + description) ───── */}
      <Dialog open={!!editingAsset} onOpenChange={(v) => !v && closeEditAsset()}>
        <DialogContent>
          {editingAsset && templatesTarget && (
            <>
              <DialogHeader
                title={t("skills.manage.editAssetTitle")}
                description={t("skills.manage.editAssetDesc")}
                onClose={closeEditAsset}
              />
              <div style={{ display: "grid", gap: 16, marginTop: 20 }}>
                <div>
                  <Label>{t("skills.manage.assetLabel.name")}</Label>
                  <Input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder={t("skills.manage.assetName.placeholder")}
                  />
                </div>
                <div>
                  <Label>{t("skills.manage.assetLabel.desc")}</Label>
                  <Textarea
                    rows={3}
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    placeholder={t("skills.manage.assetDesc.placeholder")}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="secondary" onClick={closeEditAsset}>
                  {t("skills.manage.cancel")}
                </Button>
                <Button onClick={() => onSaveEditAsset(templatesTarget)}>{t("skills.manage.save")}</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
      {/* Community marketplace dialog */}
      <Dialog open={communityOpen} onOpenChange={setCommunityOpen}>
        <DialogContent>
          <DialogHeader
            title={t("skills.community.dialogTitleFmt", { q: communityQ || t("skills.community.dialogTitleAll") })}
            description={t("skills.community.dialogDesc")}
            onClose={() => setCommunityOpen(false)}
          />
          {/* 健康监控条：把后端的 `__health__` 错误展示出来，提示用户 */}
          {Object.keys(healthErrors).length > 0 && (
            <div
              style={{
                marginTop: 14,
                padding: "10px 12px",
                borderRadius: "var(--radius-sm)",
                background: "rgba(234, 179, 8, 0.10)",
                border: "1px solid rgba(234, 179, 8, 0.35)",
                fontSize: 12,
                color: "#854d0e",
                lineHeight: 1.6,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                {t("skills.community.healthWarning")}
              </div>
              {Object.entries(healthErrors).map(([src, msg]) => (
                <div key={src}>
                  · <b>{SOURCE_STYLE[src]?.labelKey ? t(SOURCE_STYLE[src]!.labelKey) : src}</b>: {String(msg)}
                </div>
              ))}
              {healthErrors.anthropic || healthErrors.findskill ? (
                <div style={{ marginTop: 4, color: "#92400e" }}>
                  {t("skills.community.healthGitTip").split("GITHUB_TOKEN")[0]}
                  <code>GITHUB_TOKEN</code>
                  {t("skills.community.healthGitTip").split("GITHUB_TOKEN")[1] || ""}
                </div>
              ) : null}
            </div>
          )}
          <div
            style={{
              marginTop: 18,
              display: "flex",
              flexDirection: "column",
              gap: 8,
              maxHeight: 460,
              overflowY: "auto",
            }}
          >
            {displayResults.length === 0 ? (
              <div
                style={{
                  textAlign: "center",
                  color: "var(--fg-subtle)",
                  padding: 40,
                  fontSize: 13,
                }}
              >
                {t("skills.community.empty")}
              </div>
            ) : (
              displayResults.map((r, i) => renderCommunityCard(r, i))
            )}
          </div>
          <DialogFooter>
            <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginRight: "auto" }}>
              {t("skills.community.totalFmt", { n: displayResults.length })}
            </div>
            <Button variant="secondary" onClick={() => setCommunityOpen(false)}>
              {t("skills.community.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}
