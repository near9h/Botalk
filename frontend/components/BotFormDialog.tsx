"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Input,
  Label,
  Select,
  SelectOption,
  Textarea,
  useToast,
} from "@/components/ui";
import { api, Bot, KnowledgeBase, ModelInfo, Skill, SkillAsset } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: Bot | null;
  onSaved: () => Promise<void> | void;
};

// Right-pane list pagination. 5 keeps the dialog to a single screen on
// 1080p while still letting the user see enough cards to make a pick.
// Tuned against skill / KB card heights (~110–140px) plus 8px gap.
const PAGE_SIZE = 5;

/**
 * Create / edit a bot. While editing, lets the user pick which skills
 * to enable on this bot. Selected skills are saved via PUT
 * /api/bots/{id}/skills.
 */
export function BotFormDialog({ open, onOpenChange, initial, onSaved }: Props) {
  const toast = useToast();
  const { t } = useI18n();

  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("🤖");
  const [persona, setPersona] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [temperature, setTemperature] = useState(0.7);
  const [paramsText, setParamsText] = useState("{}");

  const [models, setModels] = useState<ModelInfo[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<number[]>([]);
  // Stage 5: KB tab. `kbs` is the full list the user can mount; the
  // `selectedKbPublicIds` mirrors `initial.kb_public_ids` (or starts
  // empty for a new bot). The "skills" / "knowledge" tabs are
  // mutually exclusive — a bot can mount skills OR KBs without one
  // polluting the other. We track wire-facing public_ids (strings)
  // because that's what the API expects on the PATCH payload.
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKbPublicIds, setSelectedKbPublicIds] = useState<string[]>([]);
  const [rightTab, setRightTab] = useState<"skills" | "knowledge">("skills");
  // Local-only fuzzy filter for the right-pane lists. Skills/KBs are
  // fetched in full on dialog open (see the load effect below), so we
  // never need to round-trip to the server just to filter — keeping
  // typing instant. Each tab keeps its own query so switching back
  // doesn't lose what you typed.
  const [skillQuery, setSkillQuery] = useState("");
  const [kbQuery, setKbQuery] = useState("");
  // Pagination state per tab. The list itself is small (skills/KBs are
  // typically < 20 entries) but each card is tall — paginating keeps the
  // dialog a single screen and lets us surface a real "N / M selected"
  // without forcing the user to scroll past a long list. 5 / page.
  const [skillPage, setSkillPage] = useState(1);
  const [kbPage, setKbPage] = useState(1);
  const [isPublic, setIsPublic] = useState(false);
  const [me, setMe] = useState<{ id: number; role: "admin" | "user" } | null>(null);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState(false);

  // 拉一下当前用户信息，用来决定能不能改 is_public。
  useEffect(() => {
    if (!open) return;
    api.me().then(setMe).catch(() => setMe(null));
  }, [open]);

  // Reset / hydrate form when the target bot changes.
  useEffect(() => {
    if (!open) return;
    setErrors({});
    if (initial) {
      setName(initial.name);
      setEmoji(initial.emoji);
      setPersona(initial.persona);
      setModel(initial.model);
      setTemperature(initial.temperature);
      setParamsText(JSON.stringify(initial.params || {}, null, 2));
      setIsPublic(Boolean(initial.is_public));
      // Stage 5: hydrate the KB selection from the server-rendered
      // `kb_public_ids` array (see api.bots patch response). Fall
      // back to empty when the field isn't present (older payloads).
      setSelectedKbPublicIds(
        Array.isArray(initial.kb_public_ids) ? initial.kb_public_ids : [],
      );
    } else {
      setName("");
      setEmoji("🤖");
      setPersona("");
      setModel("gpt-4o");
      setTemperature(0.7);
      setParamsText("{}");
      setSelectedSkillIds([]);
      setSelectedKbPublicIds([]);
      setSkillQuery("");
      setKbQuery("");
      setSkillPage(1);
      setKbPage(1);
      setIsPublic(false);
    }
  }, [open, initial]);

  const canTogglePublic =
    initial && (me?.role === "admin" || me?.id === initial.owner_id);

  // Pull the available skill + model lists once when the dialog opens. We
  // also re-load the bot's currently-selected skills so the checkboxes
  // reflect what was saved on the backend, not stale local state.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    (async () => {
      try {
        const [all, current, modelsResp, kbsResp] = await Promise.all([
          api.listSkills(),
          initial ? api.getBotSkills(initial.id) : Promise.resolve([]),
          api.listModels().catch(() => null),
          // Stage 5: KB list — backend enforces visibility, so an
          // unprivileged user only sees their own + is_public KBs.
          api.listKbs().catch(() => []),
        ]);
        if (!alive) return;
        setSkills(all);
        setModels(modelsResp?.data ?? []);
        setKbs(kbsResp ?? []);
        const enabledIds = current
          .filter((bs) => bs.enabled)
          .map((bs) => bs.skill.id);
        setSelectedSkillIds(enabledIds);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.push({ title: "加载技能失败", description: msg, variant: "error" });
      }
    })();
    return () => {
      alive = false;
    };
  }, [open, initial, toast]);

  // Filter helpers — case-insensitive substring match across name +
  // description (KB list also tags in description). Substring is
  // enough at this size; if the lists ever grow past a few hundred
  // we'd swap to a proper fuzzy matcher.
  const filteredSkills = useMemo(() => {
    const q = skillQuery.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter((s) => {
      const hay = `${s.name} ${s.description || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [skills, skillQuery]);

  const filteredKbs = useMemo(() => {
    const q = kbQuery.trim().toLowerCase();
    if (!q) return kbs;
    return kbs.filter((k) => {
      const hay = `${k.name} ${k.description || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [kbs, kbQuery]);

  // Paged slices + total page counts. Resetting the page to 1 inside the
  // effect below means typing in the search box automatically jumps back
  // to the first page; switching tabs resets via the form-hydrate effect.
  const skillPageCount = Math.max(1, Math.ceil(filteredSkills.length / PAGE_SIZE));
  const kbPageCount = Math.max(1, Math.ceil(filteredKbs.length / PAGE_SIZE));
  const pagedSkills = useMemo(
    () =>
      filteredSkills.slice(
        (skillPage - 1) * PAGE_SIZE,
        skillPage * PAGE_SIZE,
      ),
    [filteredSkills, skillPage],
  );
  const pagedKbs = useMemo(
    () =>
      filteredKbs.slice(
        (kbPage - 1) * PAGE_SIZE,
        kbPage * PAGE_SIZE,
      ),
    [filteredKbs, kbPage],
  );

  // Keep `skillPage` in [1, skillPageCount] even when filter shrinks the
  // list below the current page; same for KBs.
  useEffect(() => {
    if (skillPage > skillPageCount) setSkillPage(1);
  }, [skillPage, skillPageCount]);
  useEffect(() => {
    if (kbPage > kbPageCount) setKbPage(1);
  }, [kbPage, kbPageCount]);

  const modelOptions = useMemo<SelectOption[]>(
    () =>
      models.map((m) => ({
        value: m.id,
        label: m.id,
        description: `${m.vendor || m.owned_by || "unknown"} · ${
          m.owned_by || ""
        }`.replace(/·\s*$/, ""),
      })),
    [models],
  );

  const toggleSkill = (id: number) => {
    setSelectedSkillIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  // Wrap the raw search setters so typing jumps to page 1. Without this
  // a search that matches only page 2+ would silently show nothing.
  const onSkillQueryChange = (v: string) => {
    setSkillQuery(v);
    setSkillPage(1);
  };
  const onKbQueryChange = (v: string) => {
    setKbQuery(v);
    setKbPage(1);
  };

  // 用当前「名称」调 NewAPI 生成一段默认人设，已填的内容会被覆盖
  // （编辑模式下同样适用：覆盖该 bot 当前的人设）。
  const generatePersona = async () => {
    const cleanName = name.trim();
    if (!cleanName) {
      toast.push({ title: "请先填写机器人名称", variant: "error" });
      return;
    }
    if (persona.trim() && !confirm("将覆盖当前人设内容，是否继续？")) {
      return;
    }
    setGenerating(true);
    try {
      const res = await api.generatePersona({
        name: cleanName,
        // auto 让后端启发式从 name + hint 决定人设语种：
        // 中文名 → 中文人设；英文名 → 英文人设。
        language: "auto",
      });
      setPersona(res.persona);
      toast.push({
        title: "已生成默认人设",
        description: `模型 ${res.model} · ${res.latency_ms}ms`,
        variant: "success",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "人设生成失败", description: msg, variant: "error" });
    } finally {
      setGenerating(false);
    }
  };

  const onSubmit = async () => {
    setErrors({});
    const cleanName = name.trim();
    if (!cleanName) {
      setErrors({ name: "请填写机器人名称" });
      return;
    }
    let parsedParams: Record<string, unknown> = {};
    if (paramsText.trim() && paramsText.trim() !== "{}") {
      try {
        parsedParams = JSON.parse(paramsText);
      } catch {
        setErrors({ params: "params 不是合法 JSON" });
        return;
      }
    }
    const body = {
      name: cleanName,
      avatar_url: null as string | null,
      emoji: emoji || "🤖",
      persona,
      model,
      temperature,
      params: parsedParams,
      is_public: canTogglePublic ? isPublic : undefined,
    };
    setSaving(true);
    try {
      let botId = initial?.id;
      if (initial) {
        await api.updateBot(initial.id, body);
      } else {
        const created = await api.createBot(body);
        botId = created.id;
      }
      if (botId != null) {
        // Save the enabled skill set in one shot. backend returns the
        // final list so we can re-render the parent without a refetch.
        await api.setBotSkills(botId, selectedSkillIds);
        // Stage 5: persist KB mounts. Backend treats `kb_public_ids`
        // as a full overwrite (absent = no change; [] = unmount all;
        // list = idempotent bind). Sending the same list twice is a
        // no-op so we don't bother diffing locally.
        await api.updateBot(
          botId,
          { kb_public_ids: selectedKbPublicIds } as Partial<Bot>,
        );
      }
      toast.push({
        title: initial ? "已保存" : "已创建",
        description: `机器人「${body.name}」${initial ? "已更新" : "已加入你的机器人列表"}`,
        variant: "success",
      });
      await onSaved();
      onOpenChange(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "保存失败", description: msg, variant: "error" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} maxWidth={900}>
      <DialogContent>
        <DialogHeader
          title={initial ? "编辑机器人" : "新建机器人"}
          description={initial ? "修改人设、模型、技能" : "起名 + 配技能，几秒钟就能拉进群"}
          onClose={() => onOpenChange(false)}
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
            gap: 24,
            marginTop: 20,
            alignItems: "stretch",
          }}
        >
          {/* 左栏：基本信息 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ width: 80 }}>
                <Label>头像</Label>
                <Input value={emoji} onChange={(e) => setEmoji(e.target.value)} maxLength={4} />
              </div>
              <div style={{ flex: 1 }}>
                <Label>名称</Label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="如：高级开发"
                />
                {errors.name && (
                  <div style={{ color: "var(--danger)", fontSize: 12, marginTop: 4 }}>
                    {errors.name}
                  </div>
                )}
              </div>
            </div>
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 6,
                }}
              >
                <Label>人设</Label>
                <button
                  type="button"
                  onClick={generatePersona}
                  disabled={generating || saving}
                  title="根据当前名称自动生成默认人设"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "4px 10px",
                    fontSize: 12,
                    fontWeight: 500,
                    color: generating ? "var(--fg-subtle)" : "var(--accent)",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    cursor: generating ? "wait" : "pointer",
                  }}
                >
                  {generating ? "⏳ 生成中…" : "✨ AI 生成"}
                </button>
              </div>
              <Textarea
                rows={6}
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
                placeholder="你是一位……（点击右上角「AI 生成」自动起草）"
              />
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <Label>模型</Label>
                {modelOptions.length > 0 ? (
                  <Select
                    value={model}
                    onChange={setModel}
                    options={modelOptions}
                    placeholder="选择模型…"
                    searchable
                  />
                ) : (
                  <Input
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="例如：gpt-4o-mini"
                  />
                )}
                {modelOptions.length === 0 && (
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--fg-subtle)",
                      marginTop: 4,
                    }}
                  >
                    暂未拉到模型列表，可先手填，或到「模型」页刷新
                  </div>
                )}
              </div>
              <div style={{ width: 120 }}>
                <Label>温度</Label>
                <Input
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
              </div>
            </div>
            <div>
              <Label>params (JSON)</Label>
              <Textarea
                rows={3}
                value={paramsText}
                onChange={(e) => setParamsText(e.target.value)}
                placeholder='{"top_p": 0.9}'
              />
              {errors.params && (
                <div style={{ color: "var(--danger)", fontSize: 12, marginTop: 4 }}>
                  {errors.params}
                </div>
              )}
            </div>

            {/* 公开分享：仅 owner / admin 可见，普通用户不可改 */}
            {canTogglePublic && (
              <div
                style={{
                  padding: 12,
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border)",
                  background: isPublic
                    ? "rgba(34, 197, 94, 0.08)"
                    : "var(--surface-2)",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                }}
              >
                <input
                  id="bot-is-public"
                  type="checkbox"
                  checked={isPublic}
                  onChange={(e) => setIsPublic(e.target.checked)}
                  style={{ marginTop: 3 }}
                />
                <label
                  htmlFor="bot-is-public"
                  style={{ flex: 1, cursor: "pointer", fontSize: 13 }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>
                    🌍 公开给所有用户
                  </div>
                  <div style={{ fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.5 }}>
                    开启后，所有用户能在「机器人」页看到并使用这个 bot；
                    但只有你（创建者）和管理员能修改或删除。
                  </div>
                </label>
              </div>
            )}
          </div>

          {/* 右栏：技能 / 知识库 tab */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              minWidth: 0,
              minHeight: 0,
              borderLeft: "1px solid var(--border)",
              paddingLeft: 24,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <div style={{ display: "flex", gap: 6 }}>
                <TabButton
                  active={rightTab === "skills"}
                  onClick={() => setRightTab("skills")}
                >
                  🧩 技能
                </TabButton>
                <TabButton
                  active={rightTab === "knowledge"}
                  onClick={() => setRightTab("knowledge")}
                >
                  📚 知识库
                </TabButton>
              </div>
              <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                {rightTab === "skills"
                  ? `${selectedSkillIds.length} / ${skills.length} 已选`
                  : `${selectedKbPublicIds.length} / ${kbs.length} 已挂载`}
              </span>
            </div>
            {/* Search bar — sits outside the scroll container so it
                stays pinned at the top regardless of how long the list
                gets (and so it can claim full container width instead
                of fighting inner padding). */}
            <div style={{ marginTop: 8 }}>
              {rightTab === "skills" ? (
                <SearchBar
                  value={skillQuery}
                  onChange={onSkillQueryChange}
                  placeholder={t("botEdit.searchSkills")}
                />
              ) : (
                <SearchBar
                  value={kbQuery}
                  onChange={onKbQueryChange}
                  placeholder={t("botEdit.searchKbs")}
                />
              )}
            </div>
            <div
              style={{
                flex: 1,
                minHeight: 0,
                display: "flex",
                flexDirection: "column",
                gap: 8,
                padding: 10,
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                overflowY: "auto",
                background: "var(--surface-2)",
                marginTop: 8,
              }}
            >
              {rightTab === "skills" ? (
                skills.length === 0 ? (
                  <div
                    style={{
                      color: "var(--fg-subtle)",
                      fontSize: 12,
                      textAlign: "center",
                      padding: 24,
                    }}
                  >
                    暂无技能，请先到「技能中心」启用。
                  </div>
                ) : filteredSkills.length === 0 ? (
                  <div
                    style={{
                      color: "var(--fg-subtle)",
                      fontSize: 12,
                      textAlign: "center",
                      padding: 24,
                    }}
                  >
                    没有匹配「{skillQuery}」的技能
                  </div>
                ) : (
                  pagedSkills.map((s) => {
                    const active = selectedSkillIds.includes(s.id);
                    const assetCount = ((s.manifest?.assets as SkillAsset[]) || []).length;
                    return (
                      <label
                        key={s.id}
                        style={{
                          display: "flex",
                          gap: 10,
                          padding: 10,
                          borderRadius: "var(--radius-sm)",
                          border: active
                            ? "1px solid rgba(167, 139, 250, 0.55)"
                            : "1px solid var(--border)",
                          background: active
                            ? "rgba(167, 139, 250, 0.10)"
                            : "var(--surface-solid)",
                          cursor: "pointer",
                          transition: "all var(--transition)",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={active}
                          onChange={() => toggleSkill(s.id)}
                          style={{ marginTop: 2 }}
                        />
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{ fontSize: 16 }}>{s.icon || "🧩"}</span>
                            <span style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</span>
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--fg-subtle)",
                              marginTop: 2,
                              lineHeight: 1.4,
                            }}
                          >
                            {s.description || "（无描述）"}
                            {assetCount > 0 && (
                              <span style={{ marginLeft: 6, color: "var(--accent)" }}>
                                · {assetCount} 模板
                              </span>
                            )}
                          </div>
                        </div>
                      </label>
                    );
                  })
                )
              ) : kbs.length === 0 ? (
                <div
                  style={{
                    color: "var(--fg-subtle)",
                    fontSize: 12,
                    textAlign: "center",
                    padding: 24,
                  }}
                >
                  暂无可挂载的知识库，请先到「知识库」页创建。
                </div>
              ) : filteredKbs.length === 0 ? (
                <div
                  style={{
                    color: "var(--fg-subtle)",
                    fontSize: 12,
                    textAlign: "center",
                    padding: 24,
                  }}
                >
                  没有匹配「{kbQuery}」的知识库
                </div>
              ) : (
                pagedKbs.map((k) => {
                  const active = selectedKbPublicIds.includes(k.public_id);
                  return (
                    <label
                      key={k.public_id}
                      style={{
                        display: "flex",
                        gap: 10,
                        padding: 10,
                        borderRadius: "var(--radius-sm)",
                        border: active
                          ? "1px solid rgba(34, 197, 94, 0.55)"
                          : "1px solid var(--border)",
                        background: active
                          ? "rgba(34, 197, 94, 0.08)"
                          : "var(--surface-solid)",
                        cursor: "pointer",
                        transition: "all var(--transition)",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={active}
                        onChange={() =>
                          setSelectedKbPublicIds((prev) =>
                            prev.includes(k.public_id)
                              ? prev.filter((x) => x !== k.public_id)
                              : [...prev, k.public_id],
                          )
                        }
                        style={{ marginTop: 2 }}
                      />
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <span style={{ fontSize: 16 }}>📚</span>
                          <span style={{ fontSize: 13, fontWeight: 500 }}>
                            {k.name}
                          </span>
                          {k.is_public && (
                            <span
                              style={{
                                fontSize: 10,
                                padding: "1px 6px",
                                borderRadius: 999,
                                background: "rgba(34, 197, 94, 0.18)",
                                color: "#166534",
                              }}
                            >
                              公开
                            </span>
                          )}
                        </div>
                        <div
                          style={{
                            fontSize: 11,
                            color: "var(--fg-subtle)",
                            marginTop: 2,
                            lineHeight: 1.4,
                          }}
                        >
                          {k.description || "（无描述）"}
                          {!(k.ready_doc_count ?? 0) && (
                            <span style={{ marginLeft: 6, color: "var(--danger)" }}>
                              · 本地检索尚未就绪
                            </span>
                          )}
                        </div>
                      </div>
                    </label>
                  );
                })
              )}
            </div>
            {/* Pager sits below the scroll container so the list itself
                keeps its fixed-height chrome (header + search + pager =
                constant, only the card list scrolls when needed). */}
            <div style={{ marginTop: 8, display: "flex", justifyContent: "center" }}>
              {rightTab === "skills" ? (
                <Pager
                  page={skillPage}
                  pageCount={skillPageCount}
                  onChange={setSkillPage}
                />
              ) : (
                <Pager
                  page={kbPage}
                  pageCount={kbPageCount}
                  onChange={setKbPage}
                />
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={onSubmit} disabled={saving}>
            {saving ? "保存中…" : initial ? "保存" : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: "4px 12px",
        fontSize: 12,
        fontWeight: 500,
        borderRadius: 999,
        background: active ? "var(--accent)" : "var(--surface-solid)",
        color: active ? "white" : "var(--fg-muted)",
        border: active
          ? "1px solid var(--accent)"
          : "1px solid var(--border)",
        cursor: "pointer",
        transition: "all var(--transition)",
      }}
    >
      {children}
    </button>
  );
}

/**
 * Right-pane list filter. Local-only — never round-trips to the
 * server. Sits inside the scroll container so it stays visible at the
 * top while the user scrolls through long skill/KB lists.
 */
function SearchBar({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div style={{ position: "relative", flexShrink: 0, width: "100%" }}>
      <span
        aria-hidden
        style={{
          position: "absolute",
          left: 10,
          top: "50%",
          transform: "translateY(-50%)",
          fontSize: 13,
          color: "var(--fg-subtle)",
          pointerEvents: "none",
          zIndex: 1,
        }}
      >
        🔍
      </span>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          height: 32,
          paddingLeft: 30,
          paddingRight: value ? 28 : 12,
          fontSize: 12,
        }}
      />
      {value && (
        <button
          type="button"
          aria-label="清空搜索"
          onClick={() => onChange("")}
          style={{
            position: "absolute",
            right: 6,
            top: "50%",
            transform: "translateY(-50%)",
            width: 20,
            height: 20,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            border: "none",
            borderRadius: 999,
            background: "var(--surface-2)",
            color: "var(--fg-muted)",
            cursor: "pointer",
            fontSize: 11,
            lineHeight: 1,
            padding: 0,
            zIndex: 1,
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}

/**
 * Compact pager for the right-pane lists. Hides itself when there's
 * only one page so a 3-skill deployment doesn't get a useless control.
 * Uses prev/next + page numbers; no jumping to arbitrary pages since
 * the lists are tiny.
 */
function Pager({
  page,
  pageCount,
  onChange,
}: {
  page: number;
  pageCount: number;
  onChange: (p: number) => void;
}) {
  if (pageCount <= 1) return null;
  const go = (p: number) => {
    if (p < 1 || p > pageCount) return;
    onChange(p);
  };
  const btn = (label: string | number, target: number, opts: { disabled?: boolean; active?: boolean } = {}) => (
    <button
      key={`${label}-${target}`}
      type="button"
      disabled={opts.disabled}
      onClick={() => go(target)}
      style={{
        minWidth: 28,
        height: 24,
        padding: "0 8px",
        fontSize: 12,
        fontWeight: 500,
        border: "1px solid var(--border)",
        borderRadius: 6,
        background: opts.active ? "var(--accent)" : "var(--surface-solid)",
        color: opts.active ? "white" : opts.disabled ? "var(--fg-subtle)" : "var(--fg-muted)",
        cursor: opts.disabled ? "default" : "pointer",
        opacity: opts.disabled ? 0.5 : 1,
        transition: "all var(--transition)",
      }}
    >
      {label}
    </button>
  );
  return (
    <div style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      {btn("‹", page - 1, { disabled: page <= 1 })}
      {Array.from({ length: pageCount }, (_, i) => i + 1).map((p) =>
        btn(p, p, { active: p === page }),
      )}
      {btn("›", page + 1, { disabled: page >= pageCount })}
    </div>
  );
}