"use client";

import { CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  EmptyState,
  Input,
  Label,
  Textarea,
  useToast,
} from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { api, GroupPolicy, PolicyRule, User } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/**
 * 平台群规 / 防火墙规则 配置页（仅管理员）。
 *
 * 单行 `system_policies` 表 → 整表替换（PUT /api/policies）。
 * 规则条目在本地列表里编辑，点「保存」一次性提交。
 *
 * 「注入效果预览」直接展示后端用同一套渲染逻辑算出的文本
 * （`GroupPolicy.preview`），保证与真正注入 system prompt 的内容一致，
 * 不在前端复刻渲染规则。
 */
export default function PoliciesAdminPage() {
  const toast = useToast();
  const { t } = useI18n();

  const [me, setMe] = useState<User | null>(null);
  const [policy, setPolicy] = useState<GroupPolicy | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [rules, setRules] = useState<PolicyRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [u, p] = await Promise.all([api.me(), api.getPolicy()]);
      setMe(u);
      setPolicy(p);
      setEnabled(p.enabled);
      setRules(p.rules);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({
        title: t("policy.loadFail"),
        description: msg,
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    load();
  }, [load]);

  /** 本地草稿与已保存版本是否有差异 —— 用于提示「预览为上次保存的效果」。 */
  const dirty = useMemo(() => {
    if (!policy) return false;
    if (policy.enabled !== enabled) return true;
    if (policy.rules.length !== rules.length) return true;
    return rules.some((r, i) => {
      const saved = policy.rules[i];
      if (!saved) return true;
      return (
        (saved.title || "") !== (r.title || "") ||
        (saved.content || "") !== (r.content || "") ||
        Boolean(saved.enabled) !== Boolean(r.enabled)
      );
    });
  }, [policy, enabled, rules]);

  const patchRule = (idx: number, patch: Partial<PolicyRule>) => {
    setRules((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRule = () => {
    setRules((prev) => [
      ...prev,
      { id: null, title: "", content: "", enabled: true },
    ]);
  };

  const removeRule = (idx: number) => {
    setRules((prev) => prev.filter((_, i) => i !== idx));
  };

  const moveRule = (idx: number, dir: -1 | 1) => {
    setRules((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    try {
      const p = await api.updatePolicy({ enabled, rules });
      setPolicy(p);
      setEnabled(p.enabled);
      setRules(p.rules);
      toast.push({ title: t("policy.saved"), variant: "success" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({
        title: t("policy.saveFail"),
        description: msg,
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  };

  if (me && me.role !== "admin") {
    return (
      <PageShell>
        <div style={{ padding: 32 }}>
          <EmptyState
            emoji="🔒"
            title="无权限"
            description="只有管理员才能配置平台群规"
          />
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        {/* 页头 */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            marginBottom: 16,
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div>
            <h1
              style={{
                fontSize: 28,
                fontWeight: 700,
                letterSpacing: -0.5,
                marginBottom: 6,
              }}
            >
              🛡 {t("policy.title")}
            </h1>
            <p
              style={{
                color: "var(--fg-muted)",
                fontSize: 14,
                maxWidth: 720,
                lineHeight: 1.6,
              }}
            >
              {t("policy.desc")}
            </p>
          </div>
          <Button variant="secondary" onClick={load}>
            ↻ {t("common.refresh")}
          </Button>
        </div>

        {loading ? (
          <div
            style={{
              textAlign: "center",
              padding: 60,
              color: "var(--fg-subtle)",
            }}
          >
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            {t("common.loading")}
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
              gap: 16,
              alignItems: "start",
            }}
          >
            {/* 左栏：总开关 + 规则列表 */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <Card style={{ padding: 14 }}>
                <div
                  style={{ display: "flex", alignItems: "flex-start", gap: 10 }}
                >
                  <input
                    id="policy-enabled"
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                    style={{ marginTop: 3 }}
                  />
                  <label
                    htmlFor="policy-enabled"
                    style={{ flex: 1, cursor: "pointer" }}
                  >
                    <div style={{ fontWeight: 600, fontSize: 14 }}>
                      {t("policy.enabled")}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--fg-muted)",
                        marginTop: 4,
                        lineHeight: 1.5,
                      }}
                    >
                      {t("policy.enabledHint")}
                    </div>
                  </label>
                </div>
              </Card>

              <Card style={{ padding: 14 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 10,
                  }}
                >
                  <Label>{t("policy.rules")}</Label>
                  <span style={{ fontSize: 12, color: "var(--fg-subtle)" }}>
                    {t("policy.rules.count", { n: rules.length, m: 50 })}
                  </span>
                </div>

                {rules.length === 0 ? (
                  <div
                    style={{
                      color: "var(--fg-subtle)",
                      fontSize: 12,
                      textAlign: "center",
                      padding: "24px 12px",
                    }}
                  >
                    {t("policy.empty")}
                  </div>
                ) : (
                  <div
                    style={{ display: "flex", flexDirection: "column", gap: 10 }}
                  >
                    {rules.map((r, idx) => (
                      <div
                        key={idx}
                        style={{
                          border: "1px solid var(--border)",
                          borderRadius: "var(--radius-sm)",
                          background: r.enabled
                            ? "var(--surface-solid)"
                            : "var(--surface-2)",
                          padding: 10,
                          display: "flex",
                          flexDirection: "column",
                          gap: 8,
                          opacity: r.enabled ? 1 : 0.65,
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={r.enabled}
                            onChange={(e) =>
                              patchRule(idx, { enabled: e.target.checked })
                            }
                            title={t("policy.ruleEnabled")}
                          />
                          <Input
                            value={r.title}
                            maxLength={60}
                            placeholder={t("policy.ruleTitle.placeholder")}
                            onChange={(e) =>
                              patchRule(idx, { title: e.target.value })
                            }
                            style={{ flex: 1 }}
                          />
                          <button
                            type="button"
                            onClick={() => moveRule(idx, -1)}
                            disabled={idx === 0}
                            title={t("policy.moveUp")}
                            style={iconBtnStyle(idx === 0)}
                          >
                            ↑
                          </button>
                          <button
                            type="button"
                            onClick={() => moveRule(idx, 1)}
                            disabled={idx === rules.length - 1}
                            title={t("policy.moveDown")}
                            style={iconBtnStyle(idx === rules.length - 1)}
                          >
                            ↓
                          </button>
                          <button
                            type="button"
                            onClick={() => removeRule(idx)}
                            title={t("policy.remove")}
                            style={iconBtnStyle(false, true)}
                          >
                            ✕
                          </button>
                        </div>
                        <Textarea
                          value={r.content}
                          maxLength={800}
                          rows={2}
                          placeholder={t("policy.ruleContent.placeholder")}
                          onChange={(e) =>
                            patchRule(idx, { content: e.target.value })
                          }
                          style={{ minHeight: 60 }}
                        />
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ marginTop: 12 }}>
                  <Button variant="secondary" size="sm" onClick={addRule}>
                    ＋ {t("policy.addRule")}
                  </Button>
                </div>
              </Card>
            </div>

            {/* 右栏：注入预览 + 保存 */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <Card style={{ padding: 14 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 6,
                  }}
                >
                  <Label>{t("policy.preview")}</Label>
                  {dirty && (
                    <span
                      style={{ fontSize: 11, color: "var(--warning, #f59e0b)" }}
                    >
                      ● 有未保存修改
                    </span>
                  )}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--fg-subtle)",
                    marginBottom: 8,
                    lineHeight: 1.5,
                  }}
                >
                  {t("policy.preview.hint")}
                </div>
                <pre
                  style={{
                    margin: 0,
                    padding: 10,
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    fontSize: 11,
                    fontFamily: "JetBrains Mono, monospace",
                    maxHeight: 340,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    lineHeight: 1.6,
                  }}
                >
                  {policy?.preview || t("policy.preview.empty")}
                </pre>
              </Card>

              <Card style={{ padding: 14 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <Button onClick={save} disabled={saving}>
                    {saving ? t("policy.saving") : t("policy.save")}
                  </Button>
                  {policy?.updated_by_username && (
                    <span
                      style={{ fontSize: 12, color: "var(--fg-subtle)" }}
                    >
                      {t("policy.updatedBy", {
                        name: policy.updated_by_username,
                      })}
                    </span>
                  )}
                </div>
              </Card>
            </div>
          </div>
        )}
      </div>
    </PageShell>
  );
}

/** 行内小图标按钮（↑ ↓ ✕）的共用样式。 */
function iconBtnStyle(disabled: boolean, danger = false): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 26,
    height: 26,
    flex: "0 0 auto",
    borderRadius: 6,
    border: "1px solid var(--border)",
    background: "var(--surface-2)",
    color: danger ? "var(--danger, #ef4444)" : "var(--fg-muted)",
    fontSize: 12,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.4 : 1,
  };
}
