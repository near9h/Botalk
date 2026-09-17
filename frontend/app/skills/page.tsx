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

const TYPE_LABEL: Record<string, string> = {
  knowledge: "知识",
  tool: "工具",
  mcp: "MCP",
};

const CATEGORY_LABEL: Record<string, string> = {
  document: "文档",
  search: "搜索",
  crawl: "爬取",
  chart: "图表",
  mcp: "MCP",
  custom: "自定义",
};

export default function SkillsPage() {
  const toast = useToast();
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
      toast.push({ title: "加载技能失败", description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const pushErr = (title: string, e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    toast.push({ title, description: msg, variant: "error" });
  };

  const onImportSkillMdFile = async (file: File | undefined) => {
    if (!file) return;
    setImporting(true);
    try {
      const s = await api.importSkillMdFile(file);
      toast.push({ title: "已导入", description: `技能「${s.name}」已创建`, variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("导入失败", e);
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
      toast.push({ title: "已导入", description: `技能「${s.name}」已创建`, variant: "success" });
      setMdUrl("");
      setMdUrlName("");
      await refresh();
    } catch (e) {
      pushErr("导入失败", e);
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
      toast.push({ title: "已导入", description: `MCP 技能「${s.name}」已创建`, variant: "success" });
      setMcpUrl("");
      setMcpName("");
      await refresh();
    } catch (e) {
      pushErr("MCP 导入失败", e);
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
      pushErr("社区搜索失败", e);
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
        title: "已安装到技能中心",
        description: `「${installed.name}」可在机器人管理里勾选`,
        variant: "success",
      });
      // Mark this row as installed so the user sees a checkmark.
      setCommunityResults((prev) =>
        prev.map((r) => (r === item ? { ...r, __installed: installed.id } : r)),
      );
      await refresh();
    } catch (e) {
      pushErr("安装失败", e);
    } finally {
      setInstallingUrl(null);
    }
  };

  // Channel badge styling. Color-coded so the three sources are easy to
  // tell apart in a long list.
  const SOURCE_LABEL: Record<string, { label: string; bg: string; fg: string }> = {
    mcp_marketplace: { label: "MCP Marketplace", bg: "rgba(99,102,241,0.15)", fg: "#4338ca" },
    anthropic: { label: "Anthropic 官方", bg: "rgba(234,88,12,0.15)", fg: "#9a3412" },
    findskill: { label: "findskill.md", bg: "rgba(14,165,233,0.15)", fg: "#0369a1" },
  };

  // Render a result card for the marketplace dialog.
  const renderCommunityCard = (r: Record<string, unknown>, i: number) => {
    const title = String(r.title ?? r.name ?? r.id ?? `结果 ${i + 1}`);
    const url = String(r.url ?? r.html_url ?? r.homepage ?? "");
    const desc = String(r.description ?? "");
    const transport = String(r.transport ?? "streamable-http");
    const installable = Boolean(r.installable ?? !!url);
    const remoteUrl = (r.remote_url as string | undefined) ?? "";
    const githubUrl = (r.github_url as string | undefined) ?? "";
    const installedId = (r.__installed as number | undefined) ?? null;
    const busy = installingUrl === url;
    const source = String(r.source ?? "");
    const sourceMeta = SOURCE_LABEL[source] ?? { label: source || "未知", bg: "var(--surface-solid)", fg: "var(--fg-muted)" };
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
              title={`来源：${sourceMeta.label}`}
            >
              {sourceMeta.label}
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
                title="来源给出的评分（越高越好）"
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
                title="下载量 / 安装量（来源不全时用 stars 代理）"
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
                ✓ 已安装
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
                需本地部署
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
                title={`同一条目也出现在：${alsoIn.join("、")}`}
              >
                也收录于：{alsoIn.map((s) => SOURCE_LABEL[s]?.label ?? s).join("、")}
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
            {busy ? "安装中…" : "⬇ 安装"}
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
      toast.push({ title: "请填写技能名称", variant: "error" });
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
          assets: { type: "list", label: "模板资源", accept: [".md", ".markdown", ".txt"] },
        },
      });
      toast.push({ title: "已创建", description: `技能「${s.name}」已创建`, variant: "success" });
      setCreateOpen(false);
      setCName("");
      setCDesc("");
      setCInstructions("");
      await refresh();
    } catch (e) {
      pushErr("创建失败", e);
    }
  };

  const onUploadAsset = async (file: File | undefined) => {
    if (!file || !assetTarget) return;
    try {
      const s = await api.uploadSkillAsset(assetTarget.id, file);
      toast.push({ title: "模板已上传", description: `已加入「${s.name}」`, variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("上传失败", e);
    } finally {
      setAssetTarget(null);
      if (assetFileRef.current) assetFileRef.current.value = "";
    }
  };

  const onSetDefaultAsset = async (s: Skill, a: SkillAsset) => {
    try {
      await api.updateSkillAsset(s.id, a.id, { is_default: true });
      toast.push({ title: "已设为默认", description: `「${a.name}」现在是默认模板`, variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("设置失败", e);
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
      toast.push({ title: "请填写模板名称", variant: "error" });
      return;
    }
    try {
      await api.updateSkillAsset(s.id, editingAsset.id, {
        name: trimmedName,
        description: editDesc.trim(),
      });
      toast.push({ title: "已更新", description: `模板「${trimmedName}」已保存`, variant: "success" });
      await refresh();
      closeEditAsset();
    } catch (e) {
      pushErr("更新失败", e);
    }
  };

  const onDeleteAsset = async (s: Skill, a: SkillAsset) => {
    if (!confirm(`删除模板「${a.name}」？此操作不可恢复。`)) return;
    try {
      await api.deleteSkillAsset(s.id, a.id);
      toast.push({ title: "已删除", description: `模板「${a.name}」已移除`, variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("删除失败", e);
    }
  };

  const onDelete = async (s: Skill) => {
    if (!confirm(`确定删除技能「${s.name}」？`)) return;
    try {
      await api.deleteSkill(s.id);
      toast.push({ title: "已删除", description: `技能「${s.name}」已移除`, variant: "success" });
      await refresh();
    } catch (e) {
      pushErr("删除失败", e);
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
              技能中心
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              给机器人配置可复用能力：写文档、联网搜索、网页爬取、图表生成，或接入外部 MCP 服务
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button
              variant="secondary"
              size="lg"
              disabled={importing}
              onClick={() => mdFileRef.current?.click()}
            >
              ⬆ 导入 SKILL.md
            </Button>
            <Button size="lg" onClick={() => setCreateOpen(true)}>
              ＋ 新建知识技能
            </Button>
          </div>
        </div>

        {/* Import panel */}
        <Card style={{ marginBottom: 24, padding: 20 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
            <div>
              <Label>从 URL 导入 SKILL.md</Label>
              <div style={{ display: "flex", gap: 6 }}>
                <Input
                  value={mdUrl}
                  onChange={(e) => setMdUrl(e.target.value)}
                  placeholder="https://…/SKILL.md"
                />
                <Input
                  value={mdUrlName}
                  onChange={(e) => setMdUrlName(e.target.value)}
                  placeholder="名称(可选)"
                  style={{ maxWidth: 120 }}
                />
                <Button variant="secondary" onClick={onImportMdUrl} disabled={importing || !mdUrl.trim()}>
                  导入
                </Button>
              </div>
            </div>

            <div>
              <Label>接入 MCP Server</Label>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <Input
                  value={mcpUrl}
                  onChange={(e) => setMcpUrl(e.target.value)}
                  placeholder="http://host/mcp"
                />
                <Input
                  value={mcpName}
                  onChange={(e) => setMcpName(e.target.value)}
                  placeholder="名称(可选)"
                  style={{ maxWidth: 120 }}
                />
                <Button variant="secondary" onClick={onImportMcp} disabled={importing || !mcpUrl.trim()}>
                  接入
                </Button>
              </div>
            </div>

            <div>
              <Label>社区搜索（开源技能市场）</Label>
              <div style={{ display: "flex", gap: 6 }}>
                <Input
                  value={communityQ}
                  onChange={(e) => setCommunityQ(e.target.value)}
                  placeholder="搜索关键词…"
                />
                <Button variant="secondary" onClick={onCommunitySearch} disabled={importing || !communityQ.trim()}>
                  搜索
                </Button>
              </div>
            </div>
          </div>
        </Card>

        {/* Skill grid */}
        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            加载中…
          </div>
        ) : skills.length === 0 ? (
          <EmptyState
            emoji="🧩"
            title="还没有技能"
            description="导入 SKILL.md、接入 MCP Server，或新建一个知识技能"
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
                  {s.builtin && <Badge variant="info">内置</Badge>}
                </div>
                <p style={{ fontSize: 13, color: "var(--fg-muted)", lineHeight: 1.55, margin: 0, flex: 1 }}>
                  {s.description || "（无描述）"}
                </p>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Badge variant="auto">{TYPE_LABEL[s.type] ?? s.type}</Badge>
                  <Badge variant="default">{CATEGORY_LABEL[s.category] ?? s.category}</Badge>
                  <Badge variant="default">{s.bot_count ?? 0} 个机器人</Badge>
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
                      ⬆ 上传模板
                    </Button>
                  )}
                  {s.type === "knowledge" && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setTemplatesTarget(s)}
                    >
                      📋 管理模板
                      {((s.manifest?.assets as SkillAsset[]) || []).length > 0
                        ? ` (${(s.manifest?.assets as SkillAsset[]).length})`
                        : ""}
                    </Button>
                  )}
                  {!s.builtin && (
                    <Button variant="danger" size="sm" onClick={() => onDelete(s)}>
                      删除
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
            title="新建知识技能"
            description="创建一个基于提示词 + 模板的知识型技能"
            onClose={() => setCreateOpen(false)}
          />
          <div style={{ display: "grid", gap: 16, marginTop: 20 }}>
            <div>
              <Label>名称</Label>
              <Input value={cName} onChange={(e) => setCName(e.target.value)} placeholder="如：产品需求文档" />
            </div>
            <div>
              <Label>描述</Label>
              <Input value={cDesc} onChange={(e) => setCDesc(e.target.value)} placeholder="一句话说明这个技能做什么" />
            </div>
            <div>
              <Label>提示词（指令）</Label>
              <Textarea
                rows={6}
                value={cInstructions}
                onChange={(e) => setCInstructions(e.target.value)}
                placeholder="当用户要求…时，严格按模板输出…"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button onClick={onCreateSkill}>创建</Button>
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
                    title={`模板管理 · ${latest.name}`}
                    description={`为「${latest.name}」配置文档模板。多模板时在对话中点名切换，例如「用每日站会纪要」。`}
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
                        还没有模板。点击下方按钮上传第一个模板。
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
                                <Badge variant="info">默认</Badge>
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
                                  title="设为默认模板"
                                >
                                  设为默认
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
                                <span style={{ color: "var(--fg-subtle)" }}>（无描述，点击「编辑」补充一句话用途）</span>
                              )}
                            </div>
                            <div style={{ display: "flex", gap: 6 }}>
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => openEditAsset(a)}
                              >
                                ✏️ 编辑
                              </Button>
                              <Button
                                size="sm"
                                variant="danger"
                                onClick={() => onDeleteAsset(latest, a)}
                              >
                                删除
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
                        ⬆ 上传新模板
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
                title="编辑模板"
                description={`修改名称与一句话描述。模板内容请重新上传文件。`}
                onClose={closeEditAsset}
              />
              <div style={{ display: "grid", gap: 16, marginTop: 20 }}>
                <div>
                  <Label>模板名称</Label>
                  <Input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="如：每日站会纪要"
                  />
                </div>
                <div>
                  <Label>用途描述（一句话）</Label>
                  <Textarea
                    rows={3}
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    placeholder="例如：每日站会纪要：昨日进展、阻塞、今日计划"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="secondary" onClick={closeEditAsset}>
                  取消
                </Button>
                <Button onClick={() => onSaveEditAsset(templatesTarget)}>保存</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
      {/* Community marketplace dialog */}
      <Dialog open={communityOpen} onOpenChange={setCommunityOpen}>
        <DialogContent>
          <DialogHeader
            title={`🛒 社区技能市场：${communityQ || "全部"}`}
            description="聚合 MCP Marketplace.io · Anthropic 官方 skills · findskill.md 三路开源市场，已按渠道去重，按评分排序。"
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
                ⚠️ 部分渠道未返回结果
              </div>
              {Object.entries(healthErrors).map(([src, msg]) => (
                <div key={src}>
                  · <b>{SOURCE_LABEL[src]?.label ?? src}</b>: {String(msg)}
                </div>
              ))}
              {healthErrors.anthropic || healthErrors.findskill ? (
                <div style={{ marginTop: 4, color: "#92400e" }}>
                  提示：在 <code>.env</code> 配置 <code>GITHUB_TOKEN</code> 可将 GitHub 接口限流从 60/h 提升到 5000/h
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
                没有结果
              </div>
            ) : (
              displayResults.map((r, i) => renderCommunityCard(r, i))
            )}
          </div>
          <DialogFooter>
            <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginRight: "auto" }}>
              共 {displayResults.length} 条 · 已按渠道去重
            </div>
            <Button variant="secondary" onClick={() => setCommunityOpen(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}
