"use client";

import { useState } from "react";
import { Avatar, avatarColor } from "./ui";
import { BOT_TEMPLATES, BOT_TEMPLATE_LAYERS, BotTemplate } from "@/lib/botTemplates";

interface Props {
  onPick: (t: BotTemplate) => void;
}

/**
 * Pre-fill helper shown at the top of the create-bot dialog.
 * Lets the user pick a "company role" template and one-click fills the form.
 * Edit mode ignores this component (handled by parent).
 */
export function TemplatePicker({ onPick }: Props) {
  const [activeLayer, setActiveLayer] = useState<BotTemplate["layer"]>("决策层");
  const list = BOT_TEMPLATES.filter((t) => t.layer === activeLayer);

  return (
    <div
      style={{
        background: "linear-gradient(135deg, rgba(167, 139, 250, 0.06), rgba(147, 197, 253, 0.06))",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        padding: 14,
        display: "grid",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 16 }}>🏢</span>
        <span style={{ fontSize: 13, fontWeight: 600 }}>从模板快速创建</span>
        <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
          · 按组织架构选一个角色，自动填入名称、人设、温度
        </span>
      </div>

      {/* Layer tabs */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {BOT_TEMPLATE_LAYERS.map((layer) => (
          <button
            key={layer}
            onClick={() => setActiveLayer(layer)}
            style={{
              padding: "5px 12px",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 500,
              background: activeLayer === layer ? "var(--accent)" : "var(--surface-2)",
              color: activeLayer === layer ? "white" : "var(--fg-muted)",
              border: activeLayer === layer ? "1px solid var(--accent)" : "1px solid var(--border)",
              transition: "all var(--transition)",
            }}
          >
            {layer}
            <span
              style={{
                marginLeft: 6,
                fontSize: 10,
                opacity: 0.7,
                fontFamily: '"JetBrains Mono", monospace',
              }}
            >
              {BOT_TEMPLATES.filter((t) => t.layer === layer).length}
            </span>
          </button>
        ))}
      </div>

      {/* Cards for the active layer */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
          gap: 8,
        }}
      >
        {list.map((t) => (
          <button
            key={t.key}
            onClick={() => onPick(t)}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: 6,
              padding: 10,
              borderRadius: "var(--radius)",
              border: "1px solid var(--border)",
              background: "var(--surface-solid)",
              textAlign: "left",
              transition: "all var(--transition)",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent)";
              (e.currentTarget as HTMLButtonElement).style.background = "rgba(167, 139, 250, 0.06)";
              (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border)";
              (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-solid)";
              (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
            }}
            title={`用「${t.name}」模板创建`}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
              <Avatar emoji={t.emoji} size={28} color={avatarColor(t.name)} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{t.name}</div>
                <div style={{ fontSize: 10, color: "var(--fg-subtle)" }}>
                  温度 {t.temperature.toFixed(1)}
                </div>
              </div>
            </div>
            <div style={{ fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.4 }}>
              {t.tagline}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}