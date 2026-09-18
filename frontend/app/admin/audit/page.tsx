"use client";

import { useCallback, useEffect, useState } from "react";
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

const RANGES = [
  { value: "1h", label: "最近 1 小时" },
  { value: "24h", label: "最近 24 小时" },
  { value: "7d", label: "最近 7 天" },
  { value: "30d", label: "最近 30 天" },
  { value: "all", label: "全部" },
];

const ACTION_OPTIONS = [
  { value: "", label: "全部操作" },
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
  { value: "", label: "全部目标" },
  { value: "auth", label: "auth" },
  { value: "user", label: "user" },
  { value: "bot", label: "bot" },
  { value: "group", label: "group" },
  { value: "skill", label: "skill" },
  { value: "task", label: "task" },
  { value: "attachment", label: "attachment" },
];

export default function AuditAdminPage() {
  const toast = useToast();
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
      toast.push({ title: "加载审计日志失败", description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [filter, toast]);

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (me && me.role !== "admin") {
    return (
      <PageShell>
        <div style={{ padding: 32 }}>
          <EmptyState
            emoji="🔒"
            title="无权限"
            description="只有管理员才能访问审计日志"
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
              📜 审计日志
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              全量写操作流水：登录、用户增删改、bot/技能/群组/任务等
            </p>
          </div>
          <Button variant="secondary" onClick={load}>
            ↻ 刷新
          </Button>
        </div>

        {stats && (
          <Card style={{ marginBottom: 16, padding: 14 }}>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13 }}>
              <div>
                最近 24h 总计:{" "}
                <b style={{ fontSize: 18, color: "var(--accent)" }}>{stats.total_last_24h}</b>
              </div>
              <div>
                Top 操作:{" "}
                {stats.by_action.slice(0, 4).map((a) => (
                  <Badge key={a.action} variant="info" style={{ marginLeft: 6 }}>
                    {a.action} ×{a.count}
                  </Badge>
                ))}
              </div>
              <div>
                Top 用户:{" "}
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
            <div>
              <Label>时间</Label>
              <Select
                value={filter.range}
                onChange={(v) => setFilter({ ...filter, range: String(v), page: 0 })}
                options={RANGES}
              />
            </div>
            <div>
              <Label>操作</Label>
              <Select
                value={filter.action}
                onChange={(v) => setFilter({ ...filter, action: String(v), page: 0 })}
                options={ACTION_OPTIONS}
              />
            </div>
            <div>
              <Label>目标</Label>
              <Select
                value={filter.target_type}
                onChange={(v) => setFilter({ ...filter, target_type: String(v), page: 0 })}
                options={TARGET_OPTIONS}
              />
            </div>
            <div style={{ flex: 1, minWidth: 160 }}>
              <Label>用户名（模糊）</Label>
              <Input
                value={filter.actor_name}
                onChange={(e) => setFilter({ ...filter, actor_name: e.target.value, page: 0 })}
                placeholder="alice"
              />
            </div>
          </div>
        </Card>

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            加载中…
          </div>
        ) : logs.length === 0 ? (
          <EmptyState emoji="📜" title="没有日志" description="试试调整筛选条件或时间范围" />
        ) : (
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "var(--surface-2)", textAlign: "left" }}>
                  <th style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>时间</th>
                  <th style={{ padding: "8px 12px" }}>用户</th>
                  <th style={{ padding: "8px 12px" }}>角色</th>
                  <th style={{ padding: "8px 12px" }}>操作</th>
                  <th style={{ padding: "8px 12px" }}>目标</th>
                  <th style={{ padding: "8px 12px" }}>状态</th>
                  <th style={{ padding: "8px 12px" }}>IP</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((it) => {
                  const isOpen = expanded === it.id;
                  return (
                    <tbody key={it.id}>
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
                        <td style={{ padding: "8px 12px" }}>
                          {it.actor_name || <span style={{ color: "var(--fg-subtle)" }}>匿名</span>}
                        </td>
                        <td style={{ padding: "8px 12px" }}>
                          <Badge variant="default">{it.actor_role}</Badge>
                        </td>
                        <td style={{ padding: "8px 12px", fontFamily: "JetBrains Mono, monospace", fontSize: 11 }}>
                          {it.action}
                        </td>
                        <td style={{ padding: "8px 12px" }}>
                          <Badge variant="info">{it.target_type}</Badge>{" "}
                          <span style={{ color: "var(--fg-muted)" }}>{it.target_name || ""}</span>
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
                    </tbody>
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
          <div>共 {total} 条</div>
          <div style={{ display: "flex", gap: 6 }}>
            <Button
              variant="secondary"
              size="sm"
              disabled={filter.page === 0}
              onClick={() => setFilter({ ...filter, page: filter.page - 1 })}
            >
              ← 上一页
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={(filter.page + 1) * filter.page_size >= total}
              onClick={() => setFilter({ ...filter, page: filter.page + 1 })}
            >
              下一页 →
            </Button>
          </div>
        </div>
      </div>
    </PageShell>
  );
}