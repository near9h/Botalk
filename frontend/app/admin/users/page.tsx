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
import { useI18n } from "@/lib/i18n";

export default function UsersAdminPage() {
  const toast = useToast();
  const { t } = useI18n();
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
      toast.push({ title: t("users.toast.loadFail"), description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onCreate = async () => {
    if (!form.username.trim()) {
      toast.push({ title: t("users.err.usernameRequired"), variant: "error" });
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
      toast.push({ title: t("common.toast.created"), description: t("users.toast.createdFmt", { name: u.username }), variant: "success" });
      setCreateOpen(false);
      setForm({ username: "", password: "", display_name: "", email: "", role: "user" });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("users.toast.createFail"), description: msg, variant: "error" });
    } finally {
      setCreating(false);
    }
  };

  const onChangePassword = async () => {
    if (!changeTarget) return;
    if (!changeForm.n1 || changeForm.n1.length < 8) {
      toast.push({ title: t("users.pwErr.tooShort"), variant: "error" });
      return;
    }
    if (changeForm.n1 !== changeForm.n2) {
      toast.push({ title: t("users.pwErr.mismatch"), variant: "error" });
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
        title: t("users.toast.pwChanged.title"),
        description: t("users.toast.pwChangedFmt", { name: changeTarget.username }),
        variant: "success",
      });
      setChangeForm({ n1: "", n2: "" });
      setChangeTarget(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("users.toast.pwFail"), description: msg, variant: "error" });
    } finally {
      setChangeBusy(false);
    }
  };

  const onResetPassword = async (u: User) => {
    if (!confirm(t("users.resetConfirmFmt", { name: u.username }))) return;
    try {
      const out = await api.resetUserPassword(u.id);
      setLastReset(out);
      toast.push({
        title: t("users.toast.resetOk.title"),
        description: t("users.toast.resetOkFmt"),
        variant: "success",
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("users.toast.resetFail"), description: msg, variant: "error" });
    }
  };

  const onToggleStatus = async (u: User) => {
    if (u.status === "active") {
      if (!confirm(t("users.disableConfirmFmt", { name: u.username }))) return;
      try {
        await api.disableUser(u.id);
        toast.push({ title: t("users.toast.disabled.title"), description: t("users.toast.disabledFmt", { name: u.username }), variant: "success" });
        await refresh();
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.push({ title: t("users.toast.disableFail"), description: msg, variant: "error" });
      }
    } else {
      try {
        await api.enableUser(u.id);
        toast.push({ title: t("users.toast.enabled.title"), description: t("users.toast.enabledFmt", { name: u.username }), variant: "success" });
        await refresh();
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.push({ title: t("users.toast.enableFail"), description: msg, variant: "error" });
      }
    }
  };

  if (me && me.role !== "admin") {
    return (
      <PageShell>
        <div style={{ padding: 32 }}>
          <EmptyState
            emoji="🔒"
            title={t("users.noPerm.title")}
            description={t("users.noPerm.desc")}
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
              {t("users.title")}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {t("users.subtitle")}
            </p>
          </div>
          <Button size="lg" onClick={() => setCreateOpen(true)}>
            {t("users.action.new")}
          </Button>
        </div>

        {lastReset && (
          <Card style={{ marginBottom: 16, padding: 14 }}>
            <div
              style={{ fontSize: 13, marginBottom: 6 }}
              dangerouslySetInnerHTML={{ __html: t("users.resetBannerFmt", { name: lastReset.username }) }}
            />
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
              {t("users.resetAck")}
            </Button>
          </Card>
        )}

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--fg-subtle)" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>⏳</div>
            {t("common.loading")}
          </div>
        ) : users.length === 0 ? (
          <EmptyState emoji="👥" title={t("users.empty.title")} description={t("users.empty.cta")} />
        ) : (
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--surface-2)", textAlign: "left" }}>
                  <th style={{ padding: "10px 14px" }}>{t("users.table.username")}</th>
                  <th style={{ padding: "10px 14px" }}>{t("users.table.displayName")}</th>
                  <th style={{ padding: "10px 14px" }}>{t("users.table.email")}</th>
                  <th style={{ padding: "10px 14px" }}>{t("users.table.role")}</th>
                  <th style={{ padding: "10px 14px" }}>{t("users.table.status")}</th>
                  <th style={{ padding: "10px 14px" }}>{t("users.table.lastLogin")}</th>
                  <th style={{ padding: "10px 14px" }}>{t("users.table.actions")}</th>
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
                        {u.role === "admin" ? t("users.role.admin") : t("users.role.user")}
                      </Badge>
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <Badge variant={u.status === "active" ? "auto" : "default"}>
                        {u.status === "active" ? t("users.status.active") : t("users.status.disabled")}
                      </Badge>
                    </td>
                    <td style={{ padding: "10px 14px", color: "var(--fg-subtle)", fontSize: 12 }}>
                      {u.last_login_at
                        ? new Date(u.last_login_at).toLocaleString("zh-CN")
                        : t("users.never")}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <Button size="sm" variant="secondary" onClick={() => onResetPassword(u)}>
                          {t("users.action.resetPwd")}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setChangeTarget(u);
                            setChangeForm({ n1: "", n2: "" });
                          }}
                        >
                          {t("users.action.changePwd")}
                        </Button>
                        <Button
                          size="sm"
                          variant={u.status === "active" ? "danger" : "secondary"}
                          onClick={() => onToggleStatus(u)}
                          disabled={u.id === me?.id}
                          title={u.id === me?.id ? t("users.disabledTitle") : ""}
                        >
                          {u.status === "active" ? t("users.action.disable") : t("users.action.enable")}
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
            title={t("users.createDialog.title")}
            description={t("users.createDialog.desc")}
            onClose={() => setCreateOpen(false)}
          />
          <div style={{ display: "grid", gap: 14, marginTop: 18 }}>
            <div>
              <Label>{t("users.createDialog.label.username")}</Label>
              <Input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder={t("users.createDialog.username.placeholder")}
              />
            </div>
            <div>
              <Label>{t("users.createDialog.label.displayName")}</Label>
              <Input
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                placeholder={t("users.createDialog.displayName.placeholder")}
              />
            </div>
            <div>
              <Label>{t("users.createDialog.label.email")}</Label>
              <Input
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder={t("users.createDialog.email.placeholder")}
              />
            </div>
            <div>
              <Label>{t("users.createDialog.label.password")}</Label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder={t("users.createDialog.password.placeholder")}
              />
            </div>
            <div>
              <Label>{t("users.createDialog.label.role")}</Label>
              <Select
                value={form.role}
                onChange={(v) => setForm({ ...form, role: v as "admin" | "user" })}
                options={[
                  { value: "user", label: t("users.createDialog.role.user") },
                  { value: "admin", label: t("users.createDialog.role.admin") },
                ]}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              {t("users.createDialog.cancel")}
            </Button>
            <Button onClick={onCreate} disabled={creating}>
              {creating ? t("users.createDialog.creating") : t("users.createDialog.create")}
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
            title={t("users.changePwdDialog.title")}
            description={t("users.changePwdDialog.descFmt", { name: changeTarget?.username ?? "" })}
            onClose={() => setChangeTarget(null)}
          />
          <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
            <div>
              <Label>{t("users.changePwdDialog.label.new")}</Label>
              <Input
                type="password"
                value={changeForm.n1}
                onChange={(e) => setChangeForm({ ...changeForm, n1: e.target.value })}
                autoComplete="new-password"
              />
            </div>
            <div>
              <Label>{t("users.changePwdDialog.label.newConfirm")}</Label>
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
              {t("users.changePwdDialog.cancel")}
            </Button>
            <Button onClick={onChangePassword} disabled={changeBusy}>
              {changeBusy ? t("users.changePwdDialog.submitting") : t("users.changePwdDialog.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}