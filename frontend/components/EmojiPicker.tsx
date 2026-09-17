"use client";

import { useState } from "react";

const EMOJI_GROUPS: Array<{ label: string; emojis: string[] }> = [
  { label: "人/角色", emojis: ["🤖", "🧑‍💻", "🧑‍🔬", "🧑‍🎨", "🧑‍🏫", "🧑‍⚖️", "🧑‍🚀", "👨‍🍳", "🧑‍💼", "🦸", "🧙", "🧚"] },
  { label: "表情", emojis: ["😊", "🤔", "😎", "🤩", "🥳", "😴", "🤓", "🧐", "🤯", "🥸", "🫡", "🤝"] },
  { label: "动物", emojis: ["🦊", "🐱", "🐶", "🦁", "🐼", "🐨", "🦉", "🦄", "🐢", "🦋", "🐝", "🐙"] },
  { label: "自然", emojis: ["🌟", "⚡", "🔥", "🌊", "🌸", "🌳", "🍀", "🌈", "☀️", "🌙", "⛅", "❄️"] },
  { label: "物品", emojis: ["💡", "📚", "🔮", "🧠", "⚙️", "🔬", "🎯", "🎨", "🎵", "🏆", "💎", "🚀"] },
  { label: "食物", emojis: ["🍎", "🍕", "🍜", "🍣", "🍰", "☕", "🍵", "🍺", "🥗", "🍩", "🍪", "🌮"] },
  { label: "符号", emojis: ["❤️", "💜", "💙", "💚", "🧡", "💛", "🤍", "🖤", "✨", "💫", "⭐", "🌟"] },
  { label: "标志", emojis: ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"] },
];

export function EmojiPicker({ value, onChange }: { value: string; onChange: (e: string) => void }) {
  const [active, setActive] = useState(0);
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 8, background: "var(--surface-2)" }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 8, overflowX: "auto" }}>
        {EMOJI_GROUPS.map((g, i) => (
          <button
            key={g.label}
            onClick={() => setActive(i)}
            style={{
              padding: "4px 10px",
              borderRadius: 6,
              fontSize: 11,
              whiteSpace: "nowrap",
              fontWeight: 500,
              background: active === i ? "var(--accent)" : "transparent",
              color: active === i ? "white" : "var(--fg-muted)",
              transition: "all var(--transition)",
            }}
          >
            {g.label}
          </button>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: 4 }}>
        {EMOJI_GROUPS[active].emojis.map((e) => {
          const selected = e === value;
          return (
            <button
              key={e}
              onClick={() => onChange(e)}
              style={{
                aspectRatio: "1 / 1",
                fontSize: 22,
                borderRadius: 8,
                background: selected ? "rgba(167, 139, 250, 0.18)" : "transparent",
                border: selected ? "1px solid var(--accent)" : "1px solid transparent",
                transition: "all var(--transition)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
              onMouseEnter={(ev) => {
                if (!selected) (ev.currentTarget as HTMLButtonElement).style.background = "rgba(15, 23, 42, 0.05)";
              }}
              onMouseLeave={(ev) => {
                if (!selected) (ev.currentTarget as HTMLButtonElement).style.background = "transparent";
              }}
            >
              {e}
            </button>
          );
        })}
      </div>
    </div>
  );
}