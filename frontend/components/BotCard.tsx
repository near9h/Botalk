"use client";

import { useState } from "react";
import { Avatar, avatarColor, Badge, vendorBadgeVariant, Button } from "./ui";
import { Bot, vendorLabel, vendorOfModelId } from "@/lib/api";

export function BotCard({
  bot,
  onEdit,
  onDelete,
}: {
  bot: Bot;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  const [hover, setHover] = useState(false);
  const vendor = vendorOfModelId(bot.model);
  const variant = vendorBadgeVariant(vendor);
  const temperaturePct = Math.min(100, Math.max(0, (bot.temperature / 2) * 100));

  return (
    <div
      className="glass animate-fade-in"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        cursor: "default",
        transition: "transform var(--transition), box-shadow var(--transition)",
        transform: hover ? "translateY(-2px)" : "translateY(0)",
        boxShadow: hover ? "var(--shadow-lg)" : "var(--shadow)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <Avatar emoji={bot.emoji} size={44} color={avatarColor(bot.name)} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 4,
            }}
          >
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                flex: 1,
                minWidth: 0,
              }}
            >
              {bot.name}
            </div>
            {(bot.is_system || bot.is_protected) && (
              <span
                title={
                  bot.is_system
                    ? "系统机器人：不可删除，名称/模型不可修改"
                    : "受保护机器人：不可删除，名称/模型不可修改"
                }
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  padding: "2px 6px",
                  borderRadius: 999,
                  background: bot.is_system
                    ? "rgba(167, 139, 250, 0.15)"
                    : "rgba(20, 184, 166, 0.15)",
                  color: bot.is_system ? "var(--accent)" : "#0D9488",
                  border: bot.is_system
                    ? "1px solid rgba(167, 139, 250, 0.35)"
                    : "1px solid rgba(20, 184, 166, 0.40)",
                  flexShrink: 0,
                  whiteSpace: "nowrap",
                }}
              >
                {bot.is_system ? "🔒 系统" : "🛡 受保护"}
              </span>
            )}
          </div>
          <Badge variant={variant}>{vendorLabel(vendor)}</Badge>
        </div>
      </div>

      <div
        style={{
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: 11,
          color: "var(--fg-muted)",
          background: "var(--surface-2)",
          padding: "4px 8px",
          borderRadius: 6,
          border: "1px solid var(--border)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={bot.model}
      >
        {bot.model}
      </div>

      <div
        style={{
          fontSize: 12,
          color: "var(--fg-muted)",
          lineHeight: 1.5,
          minHeight: 36,
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {bot.persona || <em style={{ color: "var(--fg-subtle)" }}>未设置人设</em>}
      </div>

      <div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 10,
            color: "var(--fg-subtle)",
            marginBottom: 4,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          <span>temperature</span>
          <span style={{ fontFamily: '"JetBrains Mono", monospace' }}>{bot.temperature.toFixed(1)}</span>
        </div>
        <div
          style={{
            height: 4,
            borderRadius: 2,
            background: "var(--border-strong)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${temperaturePct}%`,
              height: "100%",
              background: `linear-gradient(90deg, var(--accent-2) 0%, var(--accent) 50%, var(--accent-4) 100%)`,
              transition: "width var(--transition)",
            }}
          />
        </div>
      </div>

      {(onEdit || onDelete) && (
        <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
          {onEdit && (
            <Button size="sm" variant="secondary" onClick={onEdit} style={{ flex: 1 }}>
              ✏️ 编辑
            </Button>
          )}
          {bot.is_system || bot.is_protected ? (
            // System / protected bots can't be deleted — show a
            // disabled lock label so the grid stays visually consistent
            // and the user knows why there's no delete button.
            <Button
              size="sm"
              variant="secondary"
              disabled
              title={
                bot.is_system
                  ? "系统机器人不可删除"
                  : "受保护机器人不可删除"
              }
              style={{ cursor: "not-allowed", opacity: 0.6 }}
            >
              {bot.is_system ? "🔒" : "🛡"}
            </Button>
          ) : (
            onDelete && (
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  if (confirm(`删除机器人「${bot.name}」？`)) onDelete();
                }}
              >
                🗑
              </Button>
            )
          )}
        </div>
      )}
    </div>
  );
}