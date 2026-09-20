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

export default function KnowledgePage() {
  const toast = useToast();
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
      toast.push({ title: "加载知识库失败", description: msg, variant: "error" });
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
      setErrors({ name: "请填写名称" });
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
        title: "已创建",
        description: `知识库「${kb.name}」已就绪`,
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
    if (!confirm(`确认删除「${kb.name}」？所有文档与 chunks 都会一并删除。`)) {
      return;
    }
    try {
      await api.deleteKb(kb.public_id);
      toast.push({
        title: "已删除",
        description: `知识库「${kb.name}」已移除`,
        variant: "success",
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "删除失败", description: msg, variant: "error" });
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
      setEditError("名称不能为空");
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
        title: "已保存",
        description: `知识库「${updated.name}」已更新`,
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
              知识库
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: 14 }}>
              {kbs.length > 0
                ? `共 ${kbs.length} 个知识库 · 上传 PDF / Word / Excel 后即可挂载到机器人`
                : "上传文档，关联到机器人，让它们在群聊里引用你的资料"}
            </p>
          </div>
          <Button
            onClick={() => setCreating(true)}
            size="lg"
          >
            <span style={{ fontSize: 16, marginRight: 4 }}>＋</span>
            新建知识库
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
            加载中…
          </div>
        ) : sorted.length === 0 ? (
          <EmptyState
            emoji="📚"
            title="还没有知识库"
            description="新建一个知识库，往里面上传 PDF / Word / Excel，再挂载到机器人。"
            action={
              <Button onClick={() => setCreating(true)} size="lg">
                ＋ 创建第一个知识库
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
                      公开
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
                  {k.description || "（无描述）"}
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
                      ? "本地检索就绪"
                      : "本地检索尚未就绪（等待首次上传）"}
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
                      title="修改知识库名称、描述、可见性"
                    >
                      编辑
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
                      title="删除整个知识库"
                    >
                      删除
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
            title="新建知识库"
            description="起一个名字 + 写几句描述，之后可以上传文档、挂载到机器人"
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
              <Label>名称</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="如：财务报销制度 / 项目模板"
                maxLength={128}
              />
              {errors.name && (
                <div style={{ color: "var(--danger)", fontSize: 12, marginTop: 4 }}>
                  {errors.name}
                </div>
              )}
            </div>
            <div>
              <Label>描述（可选）</Label>
              <Textarea
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="让协作者知道这个知识库装的是什么"
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
                  🌍 公开给所有用户挂载
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--fg-muted)",
                    lineHeight: 1.5,
                    marginTop: 2,
                  }}
                >
                  其它用户可以在他们的机器人上挂载这个知识库；
                  但只有你（创建者）和管理员能修改或删除。
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
              取消
            </Button>
            <Button onClick={onCreate} disabled={saving}>
              {saving ? "创建中…" : "创建"}
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
            title="编辑知识库"
            description="修改名称、描述、可见性。改动对所有挂载的机器人立即生效。"
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
              <Label>名称</Label>
              <Input
                value={editForm.name}
                onChange={(e) =>
                  setEditForm({ ...editForm, name: e.target.value })
                }
                placeholder="如：财务报销制度 / 项目模板"
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
              <Label>描述（可选）</Label>
              <Textarea
                rows={3}
                value={editForm.description}
                onChange={(e) =>
                  setEditForm({ ...editForm, description: e.target.value })
                }
                placeholder="让协作者知道这个知识库装的是什么"
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
                  🌍 公开给所有用户挂载
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--fg-muted)",
                    lineHeight: 1.5,
                    marginTop: 2,
                  }}
                >
                  其它用户可以在他们的机器人上挂载这个知识库；
                  但只有你（创建者）和管理员能修改或删除。
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
              取消
            </Button>
            <Button onClick={submitEdit} disabled={editSaving}>
              {editSaving ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}