"use client";

import Link from "next/link";
import { useState } from "react";
import { Avatar, avatarColor, Badge } from "./ui";
import { Bot, Group } from "@/lib/api";

const MODE_LABEL: Record<Group["mode"], { label: string; variant: "auto" | "manual" | "round_robin" }> = {
  auto: { label: "Auto · 群内轮流", variant: "auto" },
  manual: { label: "Manual · @触发", variant: "manual" },
  round_robin: { label: "Round Robin", variant: "round_robin" },
};

const GROUP_EMOJI = ["💬", "🧠", "📋", "🎨", "💼", "🔬", "🎯", "🌍", "📚", "🛠"];

function pickEmoji(seed: string, fallback: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return GROUP_EMOJI[Math.abs(h) % GROUP_EMOJI.length];
}

export function GroupCard({
  group,
  bots,
  onDelete,
}: {
  group: Group;
  bots: Bot[];
  onDelete?: () => void;
}) {
  const [hover, setHover] = useState(false);
  const memberBots = bots.filter((b) => group.bot_ids.includes(b.id));
  const mode = MODE_LABEL[group.mode];
  const emoji = pickEmoji(group.name, "💬");

  return (
    <Link
      href={`/group/${group.public_id}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="glass"
      style={{
        display: "block",
        padding: 20,
        textDecoration: "none",
        color: "inherit",
        transition: "transform var(--transition), box-shadow var(--transition)",
        transform: hover ? "translateY(-2px)" : "translateY(0)",
        boxShadow: hover ? "var(--shadow-lg)" : "var(--shadow)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
        <Avatar emoji={emoji} size={44} color={avatarColor(group.name)} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 15,
              fontWeight: 600,
              marginBottom: 4,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={group.name}
          >
            {group.name}
          </div>
          {group.description ? (
            <div
              style={{
                fontSize: 12,
                color: "var(--fg-muted)",
                lineHeight: 1.5,
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {group.description}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: "var(--fg-subtle)" }}>暂无描述</div>
          )}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
        <Badge variant={mode.variant}>{mode.label}</Badge>
        <Badge variant="info">最多 {group.max_rounds} 轮</Badge>
        {group.scope === "system" && <Badge variant="info">系统共享</Badge>}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center" }}>
          {memberBots.slice(0, 4).map((b, i) => (
            <div
              key={b.id}
              style={{
                marginLeft: i === 0 ? 0 : -8,
                border: "2px solid var(--surface-solid)",
                borderRadius: "50%",
              }}
            >
              <Avatar emoji={b.emoji} size={28} color={avatarColor(b.name)} />
            </div>
          ))}
          {memberBots.length > 4 && (
            <div
              style={{
                marginLeft: -8,
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: "var(--surface-2)",
                border: "2px solid var(--surface-solid)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 10,
                fontWeight: 600,
                color: "var(--fg-muted)",
              }}
            >
              +{memberBots.length - 4}
            </div>
          )}
          {memberBots.length === 0 && (
            <span style={{ fontSize: 12, color: "var(--fg-subtle)" }}>暂无成员</span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
            {memberBots.length} 位成员
          </span>
          {onDelete && (
            <button
              onClick={(e) => {
                e.preventDefault();
                if (confirm(`删除群组「${group.name}」？此操作不可撤销。`)) onDelete();
              }}
              style={{
                fontSize: 14,
                width: 24,
                height: 24,
                borderRadius: 6,
                color: "var(--fg-subtle)",
                transition: "all var(--transition)",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "var(--danger-bg)";
                (e.currentTarget as HTMLButtonElement).style.color = "var(--danger)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                (e.currentTarget as HTMLButtonElement).style.color = "var(--fg-subtle)";
              }}
              title="删除"
            >
              🗑
            </button>
          )}
        </div>
      </div>
    </Link>
  );
}