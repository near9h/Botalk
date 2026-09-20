"use client";

import { useState } from "react";
import { useI18n } from "@/lib/i18n";

const EMOJI_GROUPS: Array<{ labelKey: string; emojis: string[] }> = [
  { labelKey: "emoji.group.people", emojis: ["🤖", "🧑‍💻", "🧑‍🔬", "🧑‍🎨", "🧑‍🏫", "🧑‍⚖️", "🧑‍🚀", "👨‍🍳", "🧑‍💼", "🦸", "🧙", "🧚"] },
  { labelKey: "emoji.group.smileys", emojis: ["😊", "🤔", "😎", "🤩", "🥳", "😴", "🤓", "🧐", "🤯", "🥸", "🫡", "🤝"] },
  { labelKey: "emoji.group.animals", emojis: ["🦊", "🐱", "🐶", "🦁", "🐼", "🐨", "🦉", "🦄", "🐢", "🦋", "🐝", "🐙"] },
  { labelKey: "emoji.group.nature", emojis: ["🌟", "⚡", "🔥", "🌊", "🌸", "🌳", "🍀", "🌈", "☀️", "🌙", "⛅", "❄️"] },
  { labelKey: "emoji.group.objects", emojis: ["💡", "📚", "🔮", "🧠", "⚙️", "🔬", "🎯", "🎨", "🎵", "🏆", "💎", "🚀"] },
  { labelKey: "emoji.group.food", emojis: ["🍎", "🍕", "🍜", "🍣", "🍰", "☕", "🍵", "🍺", "🥗", "🍩", "🍪", "🌮"] },
  { labelKey: "emoji.group.symbols", emojis: ["❤️", "💜", "💙", "💚", "🧡", "💛", "🤍", "🖤", "✨", "💫", "⭐", "🌟"] },
  { labelKey: "emoji.group.zodiac", emojis: ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"] },
];

export function EmojiPicker({ value, onChange }: { value: string; onChange: (e: string) => void }) {
  const { t } = useI18n();
  const [active, setActive] = useState(0);
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 8, background: "var(--surface-2)" }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 8, overflowX: "auto" }}>
        {EMOJI_GROUPS.map((g, i) => (
          <button
            key={g.labelKey}
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
            {t(g.labelKey)}
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