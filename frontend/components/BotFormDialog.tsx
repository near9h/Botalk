"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Input,
  Label,
  Select,
  Textarea,
  useToast,
} from "@/components/ui";
import { api, Bot, Skill, SkillAsset } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: Bot | null;
  onSaved: () => Promise<void> | void;
};

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

  const [skills, setSkills] = useState<Skill[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

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
    } else {
      setName("");
      setEmoji("🤖");
      setPersona("");
      setModel("gpt-4o");
      setTemperature(0.7);
      setParamsText("{}");
      setSelectedSkillIds([]);
    }
  }, [open, initial]);

  // Pull the available skill list once when the dialog opens. We also
  // re-load the bot's currently-selected skills so the checkboxes reflect
  // what was saved on the backend, not stale local state.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    (async () => {
      try {
        const [all, current] = await Promise.all([
          api.listSkills(),
          initial ? api.getBotSkills(initial.id) : Promise.resolve([]),
        ]);
        if (!alive) return;
        setSkills(all);
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

  const toggleSkill = (id: number) => {
    setSelectedSkillIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader
          title={initial ? "编辑机器人" : "新建机器人"}
          description={initial ? "修改人设、模型、技能" : "起名 + 配技能，几秒钟就能拉进群"}
          onClose={() => onOpenChange(false)}
        />
        <div style={{ display: "grid", gap: 16, marginTop: 20 }}>
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
            <Label>人设</Label>
            <Textarea
              rows={6}
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              placeholder="你是一位……"
            />
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <Label>模型</Label>
              <Input value={model} onChange={(e) => setModel(e.target.value)} />
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

          {/* Skills — checkbox grid so multiple skills can be picked. */}
          <div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <Label>技能（多选）</Label>
              <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                {selectedSkillIds.length} / {skills.length} 已选
              </span>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                gap: 8,
                padding: 12,
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                maxHeight: 260,
                overflowY: "auto",
                background: "var(--surface-2)",
              }}
            >
              {skills.length === 0 ? (
                <div style={{ gridColumn: "1 / -1", color: "var(--fg-subtle)", fontSize: 12, textAlign: "center", padding: 12 }}>
                  暂无技能，请先到「技能中心」启用。
                </div>
              ) : (
                skills.map((s) => {
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
                        <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2, lineHeight: 1.4 }}>
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