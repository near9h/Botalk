"use client";

/**
 * Stage 5: Knowledge Base list page.
 *
 * Lists every KB the caller can mount on their bots (admin sees all,
 * users see their own + is_public + scope=system). Each row links to
 * the KB detail page (`/knowledge/{id}`) for upload + chunk preview.
 *
 * The header has a "+ 新建知识库" button that opens an inline dialog
 * for the create form (name + description + visibility). Each card
 * also has an inline "重命名" action that opens a small dialog
 * bound to PATCH /api/kb/{id}; deletes stay on the card too. Name
 * uniqueness is enforced server-side so the front-end just trims
 * and re-submits.
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Input,
  Label,
  Textarea,
  useToast,
  EmptyState,
} from "@/components/ui";
import { PageShell } from "@/components/Sidebar";
import { api, KnowledgeBase } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function KnowledgePage() {
  const toast = useToast();
  const { t } = useI18n();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Edit-info dialog state. Holds a snapshot of the KB being edited
  // so the title bar can show the *old* name while the user types a
  // new one; `editingId` doubles as the "is open" signal to avoid a
  // parallel boolean. The dialog edits `name`, `description`, and
  // `is_public` in one go (the backend `KbUpdate` schema has all three
  // as optional fields).
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    description: "",
    is_public: false,
  });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string>("");

  const refresh = async () => {
    setLoading(true);
    try {
      const list = await api.listKbs();
      setKbs(list);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("kb.toast.loadFail"), description: msg, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const onCreate = async () => {
    setErrors({});
    const cleanName = name.trim();
    if (!cleanName) {
      setErrors({ name: t("kb.form.err.nameRequired") });
      return;
    }
    setSaving(true);
    try {
      const kb = await api.createKb({
        name: cleanName,
        description: description.trim(),
        is_public: isPublic,
      });
      toast.push({
        title: t("common.toast.created"),
        description: t("kb.toast.createdFmt", { name: kb.name }),
        variant: "success",
      });
      setName("");
      setDescription("");
      setIsPublic(false);
      setCreating(false);
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setErrors({ create: msg });
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (kb: KnowledgeBase) => {
    if (!confirm(t("kb.deleteConfirmFmt", { name: kb.name }))) {
      return;
    }
    try {
      await api.deleteKb(kb.public_id);
      toast.push({
        title: t("common.toast.deleted"),
        description: t("kb.toast.deletedFmt", { name: kb.name }),
        variant: "success",
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: t("kb.toast.deleteFail"), description: msg, variant: "error" });
    }
  };

  const startEdit = (kb: KnowledgeBase) => {
    setEditingId(kb.public_id);
    setEditForm({
      name: kb.name,
      description: kb.description || "",
      is_public: !!kb.is_public,
    });
    setEditError("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm({ name: "", description: "", is_public: false });
    setEditError("");
  };

  const submitEdit = async () => {
    if (!editingId) return;
    const cleanName = editForm.name.trim();
    if (!cleanName) {
      setEditError(t("kb.form.err.nameBlank"));
      return;
    }
    setEditSaving(true);
    try {
      // Send every field — backend `KbUpdate` is partial so unset
      // fields stay as-is, but typing the form means we *always*
      // know the user's intent. Cleaner than diffing.
      const updated = await api.updateKb(editingId, {
        name: cleanName,
        description: editForm.description.trim(),
        is_public: editForm.is_public,
      });
      toast.push({
        title: t("common.toast.saved"),
        description: t("kb.toast.savedFmt", { name: updated.name }),
        variant: "success",
      });
      cancelEdit();
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setEditError(msg);
    } finally {
      setEditSaving(false);
    }
  };

  const sorted = useMemo(() => {
    return [...kbs].sort((a, b) => a.name.localeCompare(b.name, "zh"));
  }, [kbs]);

  return (
    <PageShell>
      <div style={{ padding: "32px 40px", margin: "0 auto", width: "100%" }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            marginBottom: 24,
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
              {t("kb.title")}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {kbs.length > 0
                ? t("kb.subtitle_countFmt", { n: kbs.length })
                : t("kb.subtitle_empty")}
            </p>
          </div>
          <Button
            onClick={() => setCreating(true)}
            size="lg"
          >
            <span style={{ fontSize: 16, marginRight: 4 }}>＋</span>
            {t("kb.action.new")}
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
        ) : sorted.length === 0 ? (
          <EmptyState
            emoji="📚"
            title={t("kb.empty.title")}
            description={t("kb.empty.desc")}
            action={
              <Button onClick={() => setCreating(true)} size="lg">
                {t("kb.empty.cta")}
              </Button>
            }
          />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 14,
            }}
          >
            {sorted.map((k) => (
              <div
                key={k.id}
                style={{
                  padding: 16,
                  borderRadius: "var(--radius)",
                  border: "1px solid var(--border)",
                  background: "var(--surface-solid)",
                  boxShadow: "var(--shadow-xs)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  transition: "all var(--transition)",
                }}
              >
                <Link
                  href={`/knowledge/${k.public_id}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    textDecoration: "none",
                    color: "var(--fg)",
                  }}
                >
                  <span style={{ fontSize: 20 }}>📚</span>
                  <span style={{ fontSize: 14, fontWeight: 600, flex: 1 }}>
                    {k.name}
                  </span>
                  {k.is_public && (
                    <span
                      style={{
                        fontSize: 10,
                        padding: "2px 8px",
                        borderRadius: 999,
                        background: "rgba(34, 197, 94, 0.18)",
                        color: "#166534",
                      }}
                    >
                      {t("kb.publicBadge")}
                    </span>
                  )}
                </Link>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--fg-subtle)",
                    lineHeight: 1.5,
                    minHeight: 32,
                  }}
                >
                  {k.description || t("kb.noDescription")}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginTop: 4,
                    fontSize: 11,
                    color: "var(--fg-subtle)",
                  }}
                >
                  <span>
                    {(k.ready_doc_count ?? 0) > 0
                      ? t("kb.ready")
                      : t("kb.notReadyFmt")}
                  </span>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        startEdit(k);
                      }}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 6,
                        border: "1px solid var(--border)",
                        background: "var(--surface-2)",
                        cursor: "pointer",
                        fontSize: 11,
                        color: "var(--fg)",
                      }}
                      title={t("kb.action.editTitle")}
                    >
                      {t("kb.action.edit")}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        void onDelete(k);
                      }}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 6,
                        border: "1px solid var(--border)",
                        background: "var(--surface-2)",
                        cursor: "pointer",
                        fontSize: 11,
                        color: "var(--danger)",
                      }}
                      title={t("kb.action.deleteTitle")}
                    >
                      {t("kb.action.delete")}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader
            title={t("kb.form.title.new")}
            description={t("kb.form.desc.new")}
            onClose={() => setCreating(false)}
          />
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              marginTop: 16,
            }}
          >
            <div>
              <Label>{t("kb.form.label.name")}</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("kb.form.name.placeholder")}
                maxLength={128}
              />
              {errors.name && (
                <div style={{ color: "var(--danger)", fontSize: 12, marginTop: 4 }}>
                  {errors.name}
                </div>
              )}
            </div>
            <div>
              <Label>{t("kb.form.label.desc")}</Label>
              <Textarea
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t("kb.form.desc.placeholder")}
                maxLength={512}
              />
            </div>
            <label
              style={{
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
                padding: 10,
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                cursor: "pointer",
                background: isPublic
                  ? "rgba(34, 197, 94, 0.06)"
                  : "var(--surface-2)",
              }}
            >
              <input
                type="checkbox"
                checked={isPublic}
                onChange={(e) => setIsPublic(e.target.checked)}
                style={{ marginTop: 3 }}
              />
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {t("kb.form.share.title")}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--fg-muted)",
                    lineHeight: 1.5,
                    marginTop: 2,
                  }}
                >
                  {t("kb.form.share.desc")}
                </div>
              </div>
            </label>
            {errors.create && (
              <div style={{ color: "var(--danger)", fontSize: 12 }}>
                {errors.create}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreating(false)}>
              {t("kb.form.cancel")}
            </Button>
            <Button onClick={onCreate} disabled={saving}>
              {saving ? t("kb.form.creating") : t("kb.form.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingId !== null}
        onOpenChange={(open) => {
          if (!open) cancelEdit();
        }}
      >
        <DialogContent>
          <DialogHeader
            title={t("kb.form.title.edit")}
            description={t("kb.form.desc.edit")}
            onClose={cancelEdit}
          />
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              marginTop: 16,
            }}
          >
            <div>
              <Label>{t("kb.form.label.name")}</Label>
              <Input
                value={editForm.name}
                onChange={(e) =>
                  setEditForm({ ...editForm, name: e.target.value })
                }
                placeholder={t("kb.form.name.placeholder")}
                maxLength={128}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !editSaving) {
                    e.preventDefault();
                    void submitEdit();
                  }
                }}
              />
            </div>
            <div>
              <Label>{t("kb.form.label.desc")}</Label>
              <Textarea
                rows={3}
                value={editForm.description}
                onChange={(e) =>
                  setEditForm({ ...editForm, description: e.target.value })
                }
                placeholder={t("kb.form.desc.placeholder")}
                maxLength={512}
              />
            </div>
            <label
              style={{
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
                padding: 10,
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                cursor: "pointer",
                background: editForm.is_public
                  ? "rgba(34, 197, 94, 0.06)"
                  : "var(--surface-2)",
              }}
            >
              <input
                type="checkbox"
                checked={editForm.is_public}
                onChange={(e) =>
                  setEditForm({ ...editForm, is_public: e.target.checked })
                }
                style={{ marginTop: 3 }}
              />
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {t("kb.form.share.title")}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--fg-muted)",
                    lineHeight: 1.5,
                    marginTop: 2,
                  }}
                >
                  {t("kb.form.share.desc")}
                </div>
              </div>
            </label>
            {editError && (
              <div style={{ color: "var(--danger)", fontSize: 12 }}>
                {editError}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={cancelEdit}>
              {t("kb.form.cancel")}
            </Button>
            <Button onClick={submitEdit} disabled={editSaving}>
              {editSaving ? t("kb.form.saving") : t("kb.form.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}