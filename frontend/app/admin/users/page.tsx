"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  EmptyState,
  Input,
  Label,
  Select,
  useToast,
} from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { api, User } from "@/lib/api";

export default function UsersAdminPage() {
  const toast = useToast();
  const [users, setUsers] = useState<User[]>([]);
  const [me, setMe] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    username: "",
    password: "",
    display_name: "",
    email: "",
    role: "user" as "user" | "admin",
  });
  const [lastReset, setLastReset] = useState<{ username: string; new_password: string } | null>(null);
  const [changeTarget, setChangeTarget] = useState<User | null>(null);
  const [changeForm, setChangeForm] = useState({ n1: "", n2: "" });
  const [changeBusy, setChangeBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [u, m] = await Promise.all([api.listUsers(), api.me()]);
      setUsers(u);
      setMe(m);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "加载用户失败", description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onCreate = async () => {
    if (!form.username.trim()) {
      toast.push({ title: "请填写用户名", variant: "error" });
      return;
    }
    setCreating(true);
    try {
      const u = await api.createUser({
        username: form.username.trim(),
        password: form.password || undefined,
        display_name: form.display_name.trim() || undefined,
        email: form.email.trim() || undefined,
        role: form.role,
      });
      toast.push({ title: "已创建", description: `用户「${u.username}」已新增`, variant: "success" });
      setCreateOpen(false);
      setForm({ username: "", password: "", display_name: "", email: "", role: "user" });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "创建失败", description: msg, variant: "error" });
    } finally {
      setCreating(false);
    }
  };

  const onChangePassword = async () => {
    if (!changeTarget) return;
    if (!changeForm.n1 || changeForm.n1.length < 8) {
      toast.push({ title: "新密码至少 8 位", variant: "error" });
      return;
    }
    if (changeForm.n1 !== changeForm.n2) {
      toast.push({ title: "两次输入的新密码不一致", variant: "error" });
      return;
    }
    setChangeBusy(true);
    try {
      const out = await api.changeUserPassword(changeTarget.id, {
        old_password: "",
        new_password: changeForm.n1,
      });
      setLastReset(out);
      toast.push({
        title: "密码已修改",
        description: `「${changeTarget.username}」的新密码：请妥善告知`,
        variant: "success",
      });
      setChangeForm({ n1: "", n2: "" });
      setChangeTarget(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "修改失败", description: msg, variant: "error" });
    } finally {
      setChangeBusy(false);
    }
  };

  const onResetPassword = async (u: User) => {
    if (!confirm(`重置「${u.username}」的密码？新密码会显示一次。`)) return;
    try {
      const out = await api.resetUserPassword(u.id);
      setLastReset(out);
      toast.push({
        title: "密码已重置",
        description: `新密码已生成：请妥善告知用户`,
        variant: "success",
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "重置失败", description: msg, variant: "error" });
    }
  };

  const onToggleStatus = async (u: User) => {
    if (u.status === "active") {
      if (!confirm(`禁用用户「${u.username}」？该用户将无法登录。`)) return;
      try {
        await api.disableUser(u.id);
        toast.push({ title: "已禁用", description: `「${u.username}」已禁用`, variant: "success" });
        await refresh();
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.push({ title: "禁用失败", description: msg, variant: "error" });
      }
    } else {
      try {
        await api.enableUser(u.id);
        toast.push({ title: "已启用", description: `「${u.username}」已恢复`, variant: "success" });
        await refresh();
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.push({ title: "启用失败", description: msg, variant: "error" });
      }
    }
  };

  if (me && me.role !== "admin") {
    return (
      <PageShell>
        <div style={{ padding: 32 }}>
          <EmptyState
            emoji="🔒"
            title="无权限"
            description="只有管理员才能访问用户管理页"
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
            marginBottom: 24,
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: -0.5, marginBottom: 6 }}>
              👥 用户管理
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              新增/启停用户、重置密码；至少保留一名管理员
            </p>
          </div>
          <Button size="lg" onClick={() => setCreateOpen(true)}>
            ＋ 新增用户
          </Button>
        </div>

        {lastReset && (
          <Card style={{ marginBottom: 16, padding: 14 }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              🔑 用户 <b>{lastReset.username}</b> 的新密码（请复制后妥善告知）：
            </div>
            <code
              style={{
                display: "inline-block",
                padding: "8px 12px",
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontSize: 14,
                fontFamily: "JetBrains Mono, monospace",
              }}
            >
              {lastReset.new_password}
            </code>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setLastReset(null)}
              style={{ marginLeft: 12 }}
            >
              我已知悉
            </Button>
          </Card>
        )}

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            加载中…
          </div>
        ) : users.length === 0 ? (
          <EmptyState emoji="👥" title="还没有用户" description="点击右上角新增" />
        ) : (
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--surface-2)", textAlign: "left" }}>
                  <th style={{ padding: "10px 14px" }}>用户名</th>
                  <th style={{ padding: "10px 14px" }}>显示名</th>
                  <th style={{ padding: "10px 14px" }}>邮箱</th>
                  <th style={{ padding: "10px 14px" }}>角色</th>
                  <th style={{ padding: "10px 14px" }}>状态</th>
                  <th style={{ padding: "10px 14px" }}>最后登录</th>
                  <th style={{ padding: "10px 14px" }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr
                    key={u.id}
                    style={{ borderTop: "1px solid var(--border)" }}
                  >
                    <td style={{ padding: "10px 14px", fontWeight: 600 }}>{u.username}</td>
                    <td style={{ padding: "10px 14px", color: "var(--fg-muted)" }}>
                      {u.display_name || "—"}
                    </td>
                    <td style={{ padding: "10px 14px", color: "var(--fg-muted)" }}>
                      {u.email || "—"}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <Badge variant={u.role === "admin" ? "info" : "default"}>
                        {u.role === "admin" ? "管理员" : "普通用户"}
                      </Badge>
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <Badge variant={u.status === "active" ? "auto" : "default"}>
                        {u.status === "active" ? "正常" : "已禁用"}
                      </Badge>
                    </td>
                    <td style={{ padding: "10px 14px", color: "var(--fg-subtle)", fontSize: 12 }}>
                      {u.last_login_at
                        ? new Date(u.last_login_at).toLocaleString("zh-CN")
                        : "从未"}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <Button size="sm" variant="secondary" onClick={() => onResetPassword(u)}>
                          🔑 重置密码
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setChangeTarget(u);
                            setChangeForm({ n1: "", n2: "" });
                          }}
                        >
                          ✏️ 修改密码
                        </Button>
                        <Button
                          size="sm"
                          variant={u.status === "active" ? "danger" : "secondary"}
                          onClick={() => onToggleStatus(u)}
                          disabled={u.id === me?.id}
                          title={u.id === me?.id ? "不能对自己操作" : ""}
                        >
                          {u.status === "active" ? "禁用" : "启用"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader
            title="新增用户"
            description="密码留空将自动生成 12 位随机密码并显示一次"
            onClose={() => setCreateOpen(false)}
          />
          <div style={{ display: "grid", gap: 14, marginTop: 18 }}>
            <div>
              <Label>用户名 *</Label>
              <Input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="alice"
              />
            </div>
            <div>
              <Label>显示名</Label>
              <Input
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                placeholder="艾丽斯"
              />
            </div>
            <div>
              <Label>邮箱</Label>
              <Input
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="alice@example.com"
              />
            </div>
            <div>
              <Label>密码（留空自动生成）</Label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="至少 8 位"
              />
            </div>
            <div>
              <Label>角色</Label>
              <Select
                value={form.role}
                onChange={(v) => setForm({ ...form, role: v as "admin" | "user" })}
                options={[
                  { value: "user", label: "普通用户" },
                  { value: "admin", label: "管理员" },
                ]}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button onClick={onCreate} disabled={creating}>
              {creating ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={changeTarget != null}
        onOpenChange={(o) => {
          if (!o) setChangeTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader
            title="修改密码"
            description={`管理员为「${changeTarget?.username ?? ""}」设置新密码（无需原密码）`}
            onClose={() => setChangeTarget(null)}
          />
          <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
            <div>
              <Label>新密码（至少 8 位）</Label>
              <Input
                type="password"
                value={changeForm.n1}
                onChange={(e) => setChangeForm({ ...changeForm, n1: e.target.value })}
                autoComplete="new-password"
              />
            </div>
            <div>
              <Label>确认新密码</Label>
              <Input
                type="password"
                value={changeForm.n2}
                onChange={(e) => setChangeForm({ ...changeForm, n2: e.target.value })}
                autoComplete="new-password"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setChangeTarget(null)}>
              取消
            </Button>
            <Button onClick={onChangePassword} disabled={changeBusy}>
              {changeBusy ? "提交中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}