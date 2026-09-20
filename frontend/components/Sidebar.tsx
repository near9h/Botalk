"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { CSSProperties, ReactNode, useEffect, useState } from "react";
import {
  Avatar,
  avatarColor,
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  IconButton,
  Input,
  Label,
  useToast,
} from "./ui";
import { SIDEBAR_EXPANDED_WIDTH, useSidebar } from "./SidebarContext";
import { useI18n } from "@/lib/i18n";
import { api, User } from "@/lib/api";

const NAV_KEYS: Array<{ href: string; key: string; icon: string }> = [
  { href: "/", key: "nav.groups", icon: "💬" },
  { href: "/bots", key: "nav.bots", icon: "🤖" },
  { href: "/knowledge", key: "nav.knowledge", icon: "📚" },
  { href: "/skills", key: "nav.skills", icon: "🧩" },
  { href: "/models", key: "nav.models", icon: "🧠" },
];

const ADMIN_KEYS: Array<{ href: string; key: string; icon: string }> = [
  { href: "/admin/users", key: "nav.adminUsers", icon: "👥" },
  { href: "/admin/audit", key: "nav.adminAudit", icon: "📜" },
  { href: "/admin/policies", key: "nav.adminPolicies", icon: "🛡" },
];

export function Sidebar() {
  const pathname = usePathname();
  const { collapsed, toggle, setCollapsed } = useSidebar();
  const { t, locale, setLocale } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [me, setMe] = useState<User | null>(null);
  const [pwOpen, setPwOpen] = useState(false);
  const [pwBusy, setPwBusy] = useState(false);
  const [pwForm, setPwForm] = useState({ old: "", n1: "", n2: "" });
  const width = collapsed ? 64 : SIDEBAR_EXPANDED_WIDTH;

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((u) => {
        if (!cancelled) setMe(u);
      })
      .catch(() => {
        /* anonymous */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const logout = async () => {
    try {
      await api.logout();
      toast.push({ title: t("sidebar.logout"), variant: "success" });
      router.replace("/login");
    } catch {
      /* ignore */
    }
  };

  const changeMyPassword = async () => {
    if (!me) return;
    if (!pwForm.n1 || pwForm.n1.length < 8) {
      toast.push({ title: t("sidebar.changePwd.errTooShort"), variant: "error" });
      return;
    }
    if (pwForm.n1 !== pwForm.n2) {
      toast.push({ title: t("sidebar.changePwd.errMismatch"), variant: "error" });
      return;
    }
    setPwBusy(true);
    try {
      await api.changeUserPassword(me.id, {
        old_password: pwForm.old,
        new_password: pwForm.n1,
      });
      toast.push({
        title: t("sidebar.changePwd.ok"),
        description: t("sidebar.changePwd.okDesc"),
        variant: "success",
      });
      setPwForm({ old: "", n1: "", n2: "" });
      setPwOpen(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("sidebar.changePwd.fail"), description: msg, variant: "error" });
    } finally {
      setPwBusy(false);
    }
  };

  return (
    <aside
      className="glass"
      style={{
        width,
        minWidth: width,
        maxWidth: width,
        height: "100vh",
        position: "sticky",
        top: 0,
        flexShrink: 0,
        transition: "width var(--transition-slow), min-width var(--transition-slow), max-width var(--transition-slow)",
        borderRadius: 0,
        borderRight: "1px solid var(--border)",
        borderTop: 0,
        borderBottom: 0,
        borderLeft: 0,
        padding: collapsed ? "16px 8px" : "20px",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
      onMouseLeave={() => {
        // No-op; reserved for future "hover-expand" if desired.
      }}
    >
      {/* Logo + collapse toggle */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: collapsed ? 0 : 10,
          marginBottom: 28,
          padding: collapsed ? "4px 0" : "4px 6px",
          justifyContent: collapsed ? "center" : "flex-start",
          position: "relative",
        }}
      >
        <Link
          href="/"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            minWidth: 0,
            flex: 1,
          }}
          title="BotGroup"
        >
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: "linear-gradient(135deg, var(--accent), var(--accent-2))",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 20,
              boxShadow: "0 4px 14px rgba(167, 139, 250, 0.35)",
              flexShrink: 0,
            }}
          >
            🤖
          </div>
          {!collapsed && (
            <div style={{ minWidth: 0, overflow: "hidden" }}>
              <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: -0.2 }}>
                BotGroup
              </div>
              <div style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                multi-bot chat
              </div>
            </div>
          )}
        </Link>
        {!collapsed && (
          <IconButton
            onClick={toggle}
            aria-label={t("sidebar.collapse")}
            title={`${t("sidebar.collapse")} (⌘\\)`}
            style={{
              width: 28,
              height: 28,
              fontSize: 14,
              color: "var(--fg-muted)",
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
            }}
          >
            ‹
          </IconButton>
        )}
      </div>

      {/* Nav */}
      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV_KEYS.map((n) => {
          const active = n.href === "/" ? pathname === "/" : pathname?.startsWith(n.href);
          const label = t(n.key);
          return (
            <Link
              key={n.href}
              href={n.href}
              title={collapsed ? label : undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: collapsed ? 0 : 10,
                justifyContent: collapsed ? "center" : "flex-start",
                padding: collapsed ? "10px 0" : "9px 12px",
                borderRadius: 10,
                fontSize: 13,
                fontWeight: 500,
                color: active ? "var(--accent)" : "var(--fg-muted)",
                background: active ? "rgba(167, 139, 250, 0.10)" : "transparent",
                transition: "all var(--transition)",
                whiteSpace: "nowrap",
                overflow: "hidden",
              }}
            >
              <span style={{ fontSize: 16, flexShrink: 0 }}>{n.icon}</span>
              {!collapsed && <span>{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Admin section — 只 admin 可见 */}
      {me?.role === "admin" && (
        <>
          {!collapsed && (
            <div
              style={{
                marginTop: 16,
                marginBottom: 4,
                fontSize: 10,
                fontWeight: 700,
                color: "var(--fg-subtle)",
                letterSpacing: 1,
                textTransform: "uppercase",
                paddingLeft: 12,
              }}
            >
              {t("sidebar.admin.label")}
            </div>
          )}
          <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {ADMIN_KEYS.map((n) => {
              const active = pathname?.startsWith(n.href);
              const label = t(n.key);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  title={collapsed ? label : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: collapsed ? 0 : 10,
                    justifyContent: collapsed ? "center" : "flex-start",
                    padding: collapsed ? "10px 0" : "9px 12px",
                    borderRadius: 10,
                    fontSize: 13,
                    fontWeight: 500,
                    color: active ? "var(--accent)" : "var(--fg-muted)",
                    background: active ? "rgba(167, 139, 250, 0.10)" : "transparent",
                    transition: "all var(--transition)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                  }}
                >
                  <span style={{ fontSize: 16, flexShrink: 0 }}>{n.icon}</span>
                  {!collapsed && <span>{label}</span>}
                </Link>
              );
            })}
          </nav>
        </>
      )}

      <div style={{ flex: 1 }} />

      {/* Expand button (collapsed mode) */}
      {collapsed && (
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
          <IconButton
            onClick={toggle}
            aria-label={t("sidebar.expand")}
            title={`${t("sidebar.expand")} (⌘\\)`}
            style={{
              width: 36,
              height: 36,
              fontSize: 16,
              color: "var(--fg-muted)",
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
            }}
          >
            ›
          </IconButton>
        </div>
      )}

      {/* Language switcher */}
      <div
        style={
          collapsed
            ? {
                display: "flex",
                justifyContent: "center",
                marginBottom: 8,
              }
            : {
                display: "flex",
                gap: 4,
                padding: "4px 6px",
                marginBottom: 8,
                borderRadius: 10,
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
              }
        }
        title={t("lang.label")}
      >
        {(["zh-CN", "en-US"] as const).map((code) => (
          <button
            key={code}
            onClick={() => setLocale(code)}
            title={code === "zh-CN" ? t("lang.zh") : t("lang.en")}
            style={{
              flex: collapsed ? undefined : 1,
              width: collapsed ? 32 : undefined,
              height: collapsed ? 32 : 28,
              borderRadius: 6,
              border: "1px solid transparent",
              background:
                locale === code ? "rgba(167, 139, 250, 0.12)" : "transparent",
              color: locale === code ? "var(--accent)" : "var(--fg-muted)",
              fontSize: collapsed ? 14 : 12,
              fontWeight: 500,
              cursor: "pointer",
              transition: "all var(--transition)",
            }}
          >
            {code === "zh-CN" ? "中" : "EN"}
          </button>
        ))}
      </div>

      {/* User card */}
      <div
        style={
          collapsed
            ? {
                display: "flex",
                justifyContent: "center",
                padding: "4px 0",
              }
            : {
                padding: 12,
                borderRadius: 12,
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
                display: "flex",
                alignItems: "center",
                gap: 10,
              }
        }
        title={collapsed ? me?.username ?? t("sidebar.user") : undefined}
        >
          <Avatar emoji="👤" size={32} color={avatarColor(me?.username ?? "me")} />
          {!collapsed && (
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 500 }}>
                {me?.username ?? t("sidebar.user")}
              </div>
            </div>
          )}
          {!collapsed && me && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                marginLeft: 8,
              }}
            >
              <button
                type="button"
                onClick={() => setPwOpen(true)}
                title={t("sidebar.changePwd.title")}
                style={{
                  border: "1px solid var(--border)",
                  background: "transparent",
                  color: "var(--fg-muted)",
                  borderRadius: 6,
                  padding: "4px 8px",
                  fontSize: 11,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                {t("sidebar.changePwd.button")}
              </button>
              <button
                type="button"
                onClick={logout}
                title={t("sidebar.logout")}
                style={{
                  border: "1px solid var(--border)",
                  background: "transparent",
                  color: "var(--fg-muted)",
                  borderRadius: 6,
                  padding: "4px 8px",
                  fontSize: 11,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                {t("sidebar.logout")}
              </button>
            </div>
          )}
        </div>

      <Dialog open={pwOpen} onOpenChange={setPwOpen}>
        <DialogContent>
          <DialogHeader
            title={t("sidebar.changePwd.title")}
            description={t("sidebar.changePwd.desc", { name: me?.username ?? "" })}
            onClose={() => setPwOpen(false)}
          />
          <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
            <div>
              <Label>{t("sidebar.changePwd.current")}</Label>
              <Input
                type="password"
                value={pwForm.old}
                onChange={(e) => setPwForm({ ...pwForm, old: e.target.value })}
                autoComplete="current-password"
              />
            </div>
            <div>
              <Label>{t("sidebar.changePwd.new")}</Label>
              <Input
                type="password"
                value={pwForm.n1}
                onChange={(e) => setPwForm({ ...pwForm, n1: e.target.value })}
                autoComplete="new-password"
              />
            </div>
            <div>
              <Label>{t("sidebar.changePwd.newConfirm")}</Label>
              <Input
                type="password"
                value={pwForm.n2}
                onChange={(e) => setPwForm({ ...pwForm, n2: e.target.value })}
                autoComplete="new-password"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setPwOpen(false)}>
              {t("sidebar.changePwd.cancel")}
            </Button>
            <Button onClick={changeMyPassword} disabled={pwBusy}>
              {pwBusy ? t("sidebar.changePwd.submitting") : t("sidebar.changePwd.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  );
}

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar />
      <main style={{ flex: 1, minWidth: 0 }}>{children}</main>
    </div>
  );
}