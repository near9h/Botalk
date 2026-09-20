"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Label,
  Select,
  useToast,
} from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { api, AuditLog, User } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/** Compact Label-above-Control wrapper for the audit filter bar.
 *  Keeps label height tight so the whole bar fits in one row on a
 *  desktop without vertical-stacking each filter. `grow` lets the
 *  free-text inputs stretch to fill leftover width. */
function FilterField({
  label,
  grow,
  children,
}: {
  label: string;
  grow?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div style={grow ? { flex: "1 1 160px", minWidth: 140 } : { minWidth: 130 }}>
      <Label>{label}</Label>
      {children}
    </div>
  );
}

const RANGES = [
  { value: "1h", labelKey: "audit.range.1h" },
  { value: "24h", labelKey: "audit.range.24h" },
  { value: "7d", labelKey: "audit.range.7d" },
  { value: "30d", labelKey: "audit.range.30d" },
  { value: "all", labelKey: "audit.range.all" },
];

const ACTION_OPTIONS = [
  { value: "", labelKey: "audit.allActions" },
  { value: "auth.login", label: "auth.login" },
  { value: "auth.login.fail", label: "auth.login.fail" },
  { value: "auth.logout", label: "auth.logout" },
  { value: "user.create", label: "user.create" },
  { value: "user.update", label: "user.update" },
  { value: "user.reset_password", label: "user.reset_password" },
  { value: "user.delete", label: "user.delete" },
  { value: "bot.create", label: "bot.create" },
  { value: "bot.update", label: "bot.update" },
  { value: "bot.delete", label: "bot.delete" },
  { value: "bot.set_skills", label: "bot.set_skills" },
  { value: "group.create", label: "group.create" },
  { value: "group.update", label: "group.update" },
  { value: "group.delete", label: "group.delete" },
  { value: "skill.create", label: "skill.create" },
  { value: "skill.update", label: "skill.update" },
  { value: "skill.delete", label: "skill.delete" },
  { value: "task.create", label: "task.create" },
  { value: "task.delete", label: "task.delete" },
  { value: "chat.run", label: "chat.run" },
  { value: "attachment.upload", label: "attachment.upload" },
];

const TARGET_OPTIONS = [
  { value: "", labelKey: "audit.allTargets" },
  { value: "auth", label: "auth" },
  { value: "user", label: "user" },
  { value: "bot", label: "bot" },
  { value: "group", label: "group" },
  { value: "skill", label: "skill" },
  { value: "task", label: "task" },
  { value: "attachment", label: "attachment" },
];

const ROLE_OPTIONS = [
  { value: "", labelKey: "audit.allRoles" },
  { value: "admin", label: "admin" },
  { value: "user", label: "user" },
];

const STATUS_OPTIONS = [
  { value: "", labelKey: "audit.allStatuses" },
  { value: "success", label: "success" },
  { value: "failure", label: "failure" },
];

export default function AuditAdminPage() {
  const toast = useToast();
  const { t } = useI18n();
  const [me, setMe] = useState<User | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [stats, setStats] = useState<{
    total_last_24h: number;
    by_action: Array<{ action: string; count: number }>;
    by_actor: Array<{ actor: string; count: number }>;
  } | null>(null);

  const [filter, setFilter] = useState({
    range: "24h",
    action: "",
    target_type: "",
    actor_name: "",
    actor_role: "",
    status: "",
    ip: "",
    page: 0,
    page_size: 50,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const from = (() => {
        if (filter.range === "all") return undefined;
        const now = new Date();
        if (filter.range === "1h") now.setHours(now.getHours() - 1);
        else if (filter.range === "24h") now.setHours(now.getHours() - 24);
        else if (filter.range === "7d") now.setDate(now.getDate() - 7);
        else if (filter.range === "30d") now.setDate(now.getDate() - 30);
        return now.toISOString();
      })();

      const [data, st_data] = await Promise.all([
        api.listAuditLogs({
          action: filter.action || undefined,
          target_type: filter.target_type || undefined,
          actor_role: filter.actor_role || undefined,
          status: filter.status || undefined,
          ip: filter.ip.trim() || undefined,
          from,
          limit: filter.page_size,
          offset: filter.page * filter.page_size,
        }),
        api.getAuditStats().catch(() => null),
      ]);
      // 客户端再过滤 actor_name（后端按 actor_id 查，前端简单用名做模糊）
      let items = data.items;
      if (filter.actor_name.trim()) {
        const q = filter.actor_name.trim().toLowerCase();
        items = items.filter((it) => (it.actor_name || "").toLowerCase().includes(q));
      }
      setLogs(items);
      setTotal(data.total);
      if (st_data) setStats(st_data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("audit.toast.loadFail"), description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [filter, toast, t]);

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
  }, []);

  // Only fire the audit fetch once we know we're admin. Otherwise
  // a non-admin visitor gets a stream of 401s in the console (the
  // backend rejects /api/audit/* for the `user` role). The "无权限"
  // empty state below renders for the same case.
  useEffect(() => {
    if (me?.role === "admin") {
      load();
    }
  }, [load, me?.role]);

  if (me && me.role !== "admin") {
    return (
      <PageShell>
        <div style={{ padding: 32 }}>
          <EmptyState
            emoji="🔒"
            title={t("audit.noPerm.title")}
            description={t("audit.noPerm.desc")}
          />
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
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
            <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: -0.5, marginBottom: 6 }}>
              {t("audit.title")}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {t("audit.subtitle")}
            </p>
          </div>
          <Button variant="secondary" onClick={load}>
            {t("audit.action.refresh")}
          </Button>
        </div>

        {stats && (
          <Card style={{ marginBottom: 16, padding: 14 }}>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13 }}>
              <div>
              {t("audit.stats.last24hFmt")}{" "}
              <b style={{ fontSize: 18, color: "var(--accent)" }}>{stats.total_last_24h}</b>
            </div>
            <div>
              {t("audit.stats.topActions")}{" "}
              {stats.by_action.slice(0, 4).map((a) => (
                <Badge key={a.action} variant="info" style={{ marginLeft: 6 }}>
                  {a.action} ×{a.count}
                </Badge>
              ))}
            </div>
            <div>
              {t("audit.stats.topActors")}{" "}
              {stats.by_actor.slice(0, 4).map((a) => (
                <Badge key={a.actor} variant="default" style={{ marginLeft: 6 }}>
                  {a.actor} ×{a.count}
                </Badge>
              ))}
            </div>
            </div>
          </Card>
        )}

        <Card style={{ marginBottom: 16, padding: 14 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
            <FilterField label={t("audit.label.range")}>
              <Select
                value={filter.range}
                onChange={(v) => setFilter({ ...filter, range: String(v), page: 0 })}
                options={RANGES.map(r => ({ value: r.value, label: r.labelKey ? t(r.labelKey) : r.value }))}
              />
            </FilterField>
            <FilterField label={t("audit.label.role")}>
              <Select
                value={filter.actor_role}
                onChange={(v) => setFilter({ ...filter, actor_role: String(v), page: 0 })}
                options={ROLE_OPTIONS.map(r => ({ value: r.value, label: r.labelKey ? t(r.labelKey) : (r as any).label }))}
              />
            </FilterField>
            <FilterField label={t("audit.label.action")}>
              <Select
                value={filter.action}
                onChange={(v) => setFilter({ ...filter, action: String(v), page: 0 })}
                options={ACTION_OPTIONS.map(r => ({ value: r.value, label: r.labelKey ? t(r.labelKey) : (r as any).label }))}
              />
            </FilterField>
            <FilterField label={t("audit.label.target")}>
              <Select
                value={filter.target_type}
                onChange={(v) => setFilter({ ...filter, target_type: String(v), page: 0 })}
                options={TARGET_OPTIONS.map(r => ({ value: r.value, label: r.labelKey ? t(r.labelKey) : (r as any).label }))}
              />
            </FilterField>
            <FilterField label={t("audit.label.status")}>
              <Select
                value={filter.status}
                onChange={(v) => setFilter({ ...filter, status: String(v), page: 0 })}
                options={STATUS_OPTIONS.map(r => ({ value: r.value, label: r.labelKey ? t(r.labelKey) : (r as any).label }))}
              />
            </FilterField>
            <FilterField label={t("audit.label.actor")} grow>
              <Input
                value={filter.actor_name}
                onChange={(e) => setFilter({ ...filter, actor_name: e.target.value, page: 0 })}
                placeholder={t("audit.actor.placeholder")}
              />
            </FilterField>
            <FilterField label={t("audit.label.ip")} grow>
              <Input
                value={filter.ip}
                onChange={(e) => setFilter({ ...filter, ip: e.target.value, page: 0 })}
                placeholder={t("audit.ip.placeholder")}
              />
            </FilterField>
          </div>
        </Card>

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            {t("common.loading")}
          </div>
        ) : logs.length === 0 ? (
          <EmptyState emoji="📜" title={t("audit.empty.title")} description={t("audit.empty.desc")} />
        ) : (
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
              <tr style={{ background: "var(--surface-2)", textAlign: "left" }}>
                <th style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>{t("audit.table.time")}</th>
                <th style={{ padding: "8px 12px" }}>{t("audit.table.user")}</th>
                <th style={{ padding: "8px 12px" }}>{t("audit.table.role")}</th>
                <th style={{ padding: "8px 12px" }}>{t("audit.table.action")}</th>
                <th style={{ padding: "8px 12px" }}>{t("audit.table.target")}</th>
                <th style={{ padding: "8px 12px" }}>{t("audit.table.status")}</th>
                <th style={{ padding: "8px 12px" }}>{t("audit.table.ip")}</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((it) => {
                const isOpen = expanded === it.id;
                return (
                  <Fragment key={it.id}>
                    <tr
                      style={{
                        borderTop: "1px solid var(--border)",
                        cursor: "pointer",
                        background: isOpen ? "var(--surface-2)" : undefined,
                      }}
                      onClick={() => setExpanded(isOpen ? null : it.id)}
                    >
                      <td style={{ padding: "8px 12px", whiteSpace: "nowrap", color: "var(--fg-muted)" }}>
                        {new Date(it.occurred_at).toLocaleString("zh-CN", { hour12: false })}
                      </td>
                      <td style={{ padding: "8px 12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }}>
                        {it.actor_name || <span style={{ color: "var(--fg-subtle)" }}>{t("audit.anonymous")}</span>}
                      </td>
                      <td style={{ padding: "8px 12px" }}>
                        <Badge variant="default">{it.actor_role}</Badge>
                      </td>
                      <td style={{ padding: "8px 12px", fontFamily: "JetBrains Mono, monospace", fontSize: 11 }}>
                        {it.action}
                      </td>
                        <td style={{ padding: "8px 12px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                            <Badge variant="info" style={{ flexShrink: 0 }}>
                              {it.target_type}
                            </Badge>
                            <span
                              style={{
                                color: "var(--fg-muted)",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                minWidth: 0,
                              }}
                            >
                              {it.target_name || ""}
                            </span>
                          </div>
                        </td>
                        <td style={{ padding: "8px 12px" }}>
                          <Badge variant={it.status === "success" ? "auto" : "default"}>
                            {it.status}
                          </Badge>
                        </td>
                        <td style={{ padding: "8px 12px", color: "var(--fg-subtle)", fontSize: 11 }}>
                          {it.ip || "—"}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr style={{ background: "var(--surface-2)" }}>
                          <td colSpan={7} style={{ padding: "0 12px 12px 12px" }}>
                            <pre
                              style={{
                                margin: 0,
                                padding: 10,
                                background: "var(--surface-solid)",
                                border: "1px solid var(--border)",
                                borderRadius: 6,
                                fontSize: 11,
                                fontFamily: "JetBrains Mono, monospace",
                                maxHeight: 200,
                                overflow: "auto",
                                whiteSpace: "pre-wrap",
                              }}
                            >
                              {JSON.stringify(
                                {
                                  actor_id: it.actor_id,
                                  target_id: it.target_id,
                                  user_agent: it.user_agent,
                                  detail: it.detail,
                                },
                                null,
                                2,
                              )}
                            </pre>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 12,
            fontSize: 12,
            color: "var(--fg-muted)",
          }}
        >
          <div>{t("audit.totalFmt", { n: total })}</div>
          <div style={{ display: "flex", gap: 6 }}>
            <Button
              variant="secondary"
              size="sm"
              disabled={filter.page === 0}
              onClick={() => setFilter({ ...filter, page: filter.page - 1 })}
            >
              {t("audit.prev")}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={(filter.page + 1) * filter.page_size >= total}
              onClick={() => setFilter({ ...filter, page: filter.page + 1 })}
            >
              {t("audit.next")}
            </Button>
          </div>
        </div>
      </div>
    </PageShell>
  );
}