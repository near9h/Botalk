"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Avatar,
  avatarColor,
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Input,
  Label,
  Textarea,
  useToast,
} from "./ui";
import { api, Bot, Group } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Mode = Group["mode"];

const MODE_OPTIONS: Array<{ value: Mode; title: string; description: string; icon: string }> = [
  {
    value: "auto",
    title: "Auto",
    description: "一轮内所有机器人都按加入顺序发言；适合群聊讨论",
    icon: "🌐",
  },
  {
    value: "round_robin",
    title: "Round Robin",
    description: "每轮只让一个机器人发言，按加入顺序轮换",
    icon: "🔁",
  },
  {
    value: "manual",
    title: "Manual",
    description: "只有 @ 机器人名 才让对应机器人说话",
    icon: "🎯",
  },
];

export function GroupWizard({
  open,
  onOpenChange,
  bots,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  bots: Bot[];
  onCreated?: (g: Group) => void;
}) {
  const toast = useToast();
  const router = useRouter();
  const { t } = useI18n();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [notice, setNotice] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [maxRounds, setMaxRounds] = useState(3);
  const [selectedBots, setSelectedBots] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setStep(0);
    setName("");
    setDescription("");
    setNotice("");
    setMode("auto");
    setMaxRounds(6);
    setSelectedBots([]);
  };

  const close = () => {
    onOpenChange(false);
    setTimeout(reset, 300);
  };

  const toggleBot = (id: number) => {
    setSelectedBots((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const canNext = () => {
    if (step === 0) return name.trim().length > 0;
    if (step === 1) return true;
    if (step === 2) return selectedBots.length > 0;
    return true;
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      const g = await api.createGroup({
        name: name.trim(),
        description: description.trim() || null,
        mode,
        max_rounds: maxRounds,
        bot_ids: selectedBots,
        notice: notice.trim() || undefined,
      });
      toast.push({
        title: "群组已创建",
        description: `「${g.name}」已就绪，可以开始讨论了`,
        variant: "success",
      });
      onCreated?.(g);
      close();
      router.push(`/group/${g.public_id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.push({ title: "创建失败", description: msg, variant: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} maxWidth={720}>
      <DialogContent>
        <DialogHeader
          title="新建群组"
          description="分 4 步配置你的群聊"
          onClose={close}
        />

        {/* Stepper —— 4 列等宽网格，确保第 4 步「确认」一定可见 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            alignItems: "start",
            gap: 0,
            margin: "20px 0 24px",
            fontSize: 12,
          }}
        >
          {["基础信息", "发言模式", "选择成员", "确认"].map((label, i) => {
            const active = i === step;
            const done = i < step;
            return (
              <div
                key={label}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  minWidth: 0,
                  position: "relative",
                }}
              >
                {/* 连接线：在 badge 后面延展到下一列起点 */}
                {i < 3 && (
                  <div
                    style={{
                      position: "absolute",
                      top: 11, // 居中 badge (badge 22 高)
                      left: "calc(50% + 12px)",
                      right: "calc(-50% + 12px)",
                      height: 2,
                      background: done ? "var(--accent)" : "var(--border)",
                      transition: "background var(--transition)",
                    }}
                  />
                )}
                <div
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: "50%",
                    background: i <= step ? "var(--accent)" : "var(--surface-2)",
                    color: i <= step ? "white" : "var(--fg-muted)",
                    fontSize: 11,
                    fontWeight: 600,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    border: i <= step ? "none" : "1px solid var(--border-strong)",
                    transition: "all var(--transition)",
                    position: "relative",
                    zIndex: 1,
                  }}
                >
                  {done ? "✓" : i + 1}
                </div>
                <span
                  style={{
                    marginTop: 6,
                    fontWeight: active ? 600 : 400,
                    color: i <= step ? "var(--fg)" : "var(--fg-subtle)",
                    fontSize: 11,
                    textAlign: "center",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: "100%",
                  }}
                >
                  {label}
                </span>
              </div>
            );
          })}
        </div>

        {/* Step content */}
        <div style={{ minHeight: 280 }}>
          {step === 0 && (
            <div style={{ display: "grid", gap: 16 }}>
              <div>
                <Label htmlFor="wiz-name">群组名称</Label>
                <Input
                  id="wiz-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="如：产品讨论 / 设计评审 / 投资决策"
                  autoFocus
                />
              </div>
              <div>
                <Label htmlFor="wiz-desc">描述（可选）</Label>
                <Textarea
                  id="wiz-desc"
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="这个群组讨论什么主题？"
                />
              </div>
              <div>
                <Label htmlFor="wiz-notice">
                  {t("group.notice")}（可选）
                </Label>
                <Textarea
                  id="wiz-notice"
                  rows={3}
                  value={notice}
                  maxLength={2000}
                  onChange={(e) => setNotice(e.target.value)}
                  placeholder={t("group.notice.placeholder")}
                />
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--fg-subtle)",
                    marginTop: 4,
                    lineHeight: 1.5,
                  }}
                >
                  {t("group.notice.tip")}
                </div>
              </div>
            </div>
          )}

          {step === 1 && (
            <div style={{ display: "grid", gap: 10 }}>
              {MODE_OPTIONS.map((opt) => {
                const selected = mode === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setMode(opt.value)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      padding: 16,
                      borderRadius: "var(--radius)",
                      border: selected
                        ? "2px solid var(--accent)"
                        : "1px solid var(--border-strong)",
                      background: selected
                        ? "rgba(167, 139, 250, 0.06)"
                        : "var(--surface-solid)",
                      textAlign: "left",
                      transition: "all var(--transition)",
                    }}
                  >
                    <div style={{ fontSize: 28 }}>{opt.icon}</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>{opt.title}</div>
                      <div style={{ fontSize: 12, color: "var(--fg-muted)" }}>
                        {opt.description}
                      </div>
                    </div>
                    {selected && (
                      <div
                        style={{
                          width: 20,
                          height: 20,
                          borderRadius: "50%",
                          background: "var(--accent)",
                          color: "white",
                          fontSize: 11,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                      >
                        ✓
                      </div>
                    )}
                  </button>
                );
              })}
              <div style={{ marginTop: 8 }}>
                <Label htmlFor="wiz-rounds">最大轮次</Label>
                <Input
                  id="wiz-rounds"
                  type="number"
                  min={1}
                  max={6}
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Number(e.target.value))}
                />
                <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 6 }}>
                  一轮 = 3 个机器人依次发言（auto 模式）。建议 2–4 轮；群成员越多 token 越多。
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div>
              {bots.length === 0 ? (
                <div
                  style={{
                    padding: 24,
                    borderRadius: "var(--radius)",
                    background: "var(--surface-2)",
                    border: "1px dashed var(--border-strong)",
                    textAlign: "center",
                    color: "var(--fg-muted)",
                    fontSize: 13,
                  }}
                >
                  还没有机器人。<br />
                  先去「机器人管理」建一个。
                </div>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
                  {bots.map((b) => {
                    const selected = selectedBots.includes(b.id);
                    return (
                      <button
                        key={b.id}
                        onClick={() => toggleBot(b.id)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: 12,
                          borderRadius: "var(--radius)",
                          border: selected
                            ? "2px solid var(--accent)"
                            : "1px solid var(--border-strong)",
                          background: selected
                            ? "rgba(167, 139, 250, 0.06)"
                            : "var(--surface-solid)",
                          textAlign: "left",
                          transition: "all var(--transition)",
                        }}
                      >
                        <Avatar emoji={b.emoji} size={36} color={avatarColor(b.name)} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 500, fontSize: 13 }}>{b.name}</div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--fg-muted)",
                              fontFamily: '"JetBrains Mono", monospace',
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {b.model}
                          </div>
                        </div>
                        {selected && (
                          <div style={{ color: "var(--accent)", fontSize: 18 }}>✓</div>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
              <div style={{ marginTop: 12, fontSize: 12, color: "var(--fg-muted)" }}>
                已选 {selectedBots.length} 位机器人
              </div>
            </div>
          )}

          {step === 3 && (
            <div style={{ display: "grid", gap: 16 }}>
              <div
                className="glass"
                style={{ padding: 16, display: "flex", alignItems: "center", gap: 12 }}
              >
                <Avatar emoji="💬" size={48} color={avatarColor(name || "default")} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>{name}</div>
                  {description && (
                    <div style={{ fontSize: 12, color: "var(--fg-muted)", marginTop: 4 }}>
                      {description}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div
                  style={{
                    padding: 12,
                    borderRadius: "var(--radius)",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 }}>
                    模式
                  </div>
                  <Badge variant={mode === "auto" ? "auto" : mode === "manual" ? "manual" : "round_robin"}>
                    {MODE_OPTIONS.find((m) => m.value === mode)?.title}
                  </Badge>
                </div>
                <div
                  style={{
                    padding: 12,
                    borderRadius: "var(--radius)",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 }}>
                    最多轮次
                  </div>
                  <div style={{ fontWeight: 600, fontFamily: '"JetBrains Mono", monospace' }}>{maxRounds}</div>
                </div>
              </div>

              <div>
                <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginBottom: 8, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  成员 ({selectedBots.length})
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {selectedBots.map((id) => {
                    const b = bots.find((x) => x.id === id);
                    if (!b) return null;
                    return (
                      <div
                        key={id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "4px 10px 4px 4px",
                          background: "var(--surface-2)",
                          border: "1px solid var(--border)",
                          borderRadius: 999,
                          fontSize: 12,
                        }}
                      >
                        <Avatar emoji={b.emoji} size={20} color={avatarColor(b.name)} />
                        {b.name}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          {step > 0 && (
            <Button
              variant="secondary"
              onClick={() => setStep(step - 1)}
              disabled={submitting}
            >
              上一步
            </Button>
          )}
          {step < 3 ? (
            <Button onClick={() => setStep(step + 1)} disabled={!canNext()}>
              下一步
            </Button>
          ) : (
            <Button onClick={submit} disabled={submitting}>
              {submitting ? "创建中…" : "创建群组"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}