"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui";
import { api, User } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/**
 * Login window with two panels:
 *   - Left: a compact, professional group-chat feed. Four team-role bots
 *     (需求分析师 / 研发工程师 / 测试工程师 / 项目经理) take turns posting
 *     business messages, separated by a "正在输入…" indicator. Avatars share
 *     a single brand accent (no rainbow, no emoji) so the product reads as a
 *     serious team-collaboration tool rather than a toy. Pure DOM/CSS, no GIF.
 *   - Right: the simplified sign-in form (no OAuth).
 *
 * Background image lives in /public/login/bg.jpg (bundled at build time,
 * so the page renders without external requests).
 */
export default function LoginPage() {
  const router = useRouter();
  const toast = useToast();
  const { t } = useI18n();
  const [user, setUser] = useState<User | null>(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch {
        /* anonymous */
      } finally {
        if (!cancelled) setLoadingMe(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!loadingMe && user) router.replace("/");
  }, [loadingMe, user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setSubmitting(true);
    try {
      const me = await api.login(username.trim(), password);
      setUser(me);
      toast.push({
        title: t("login.toast.welcome"),
        description: t("login.toast.welcomeDesc", { name: me.username }),
        variant: "success",
      });
      router.replace("/");
    } catch (e2) {
      const msg = e2 instanceof Error ? e2.message : String(e2);
      toast.push({
        title: t("login.toast.fail"),
        description: msg,
        variant: "error",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        position: "relative",
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        overflow: "hidden",
        // Background image + soft tint so the white card stays readable.
        backgroundImage: "url(/login/bg.jpg)",
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      {/* Decorative gradient overlay */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at 20% 30%, rgba(167,139,250,0.25), transparent 50%), radial-gradient(ellipse at 80% 70%, rgba(96,165,250,0.20), transparent 55%), linear-gradient(135deg, rgba(255,255,255,0.55), rgba(255,255,255,0.25))",
          backdropFilter: "blur(2px)",
        }}
      />
      {/* Subtle grid (Singapore dashboard vibe) */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(rgba(167,139,250,0.10) 1px, transparent 1px), linear-gradient(90deg, rgba(167,139,250,0.10) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
          maskImage:
            "radial-gradient(ellipse at center, black 30%, transparent 80%)",
        }}
      />

      <div
        className="glass animate-scale-in"
        style={{
          position: "relative",
          width: "min(960px, 100%)",
          borderRadius: 16,
          overflow: "hidden",
          boxShadow: "0 30px 80px rgba(15, 23, 42, 0.22)",
          border: "1px solid var(--border)",
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)",
        }}
      >
        {/* Left: animated group-chat feed */}
        <div
          className="glass-strong"
          style={{
            padding: 0,
            borderRadius: 0,
            border: "none",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <ChromeBar title="BotGroup · Team Collaboration" />
          <AnimatedTerminal />
        </div>

        {/* Right: login panel */}
        <div
          style={{
            padding: 32,
            display: "flex",
            flexDirection: "column",
            gap: 16,
            background: "var(--surface)",
          }}
        >
          <ChromeBar title="login" />
          <div
            style={{
              fontSize: 24,
              fontWeight: 700,
              letterSpacing: -0.4,
              marginTop: 4,
            }}
          >
            <span style={{ color: "var(--accent)" }}>› </span>
            {t("login.title")}
          </div>
          <div style={{ fontSize: 12, color: "var(--fg-subtle)", lineHeight: 1.55 }}>
            {t("login.hint")}
          </div>

          <form
            onSubmit={submit}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              marginTop: 8,
            }}
          >
            <label
              style={{
                fontSize: 11,
                color: "var(--fg-muted)",
                fontWeight: 500,
              }}
            >
              {t("login.username")}
            </label>
            <input
              type="text"
              autoComplete="username"
              placeholder="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              style={fieldStyle}
              required
              disabled={submitting}
            />
            <label
              style={{
                fontSize: 11,
                color: "var(--fg-muted)",
                fontWeight: 500,
                marginTop: 2,
              }}
            >
              {t("login.password")}
            </label>
            <input
              type="password"
              autoComplete="current-password"
              placeholder="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={fieldStyle}
              required
              disabled={submitting}
            />
            <button
              type="submit"
              disabled={submitting}
              style={{
                marginTop: 10,
                padding: "11px 16px",
                borderRadius: 10,
                border: "none",
                background:
                  "linear-gradient(135deg, var(--accent), var(--accent-2))",
                color: "white",
                fontSize: 14,
                fontWeight: 600,
                cursor: submitting ? "wait" : "pointer",
                boxShadow: "0 6px 18px rgba(167, 139, 250, 0.35)",
                transition: "transform var(--transition), box-shadow var(--transition)",
                opacity: submitting ? 0.85 : 1,
              }}
            >
              {submitting ? t("login.submitting") : t("login.submit")}{" "}
              <span style={{ marginLeft: 6, opacity: 0.7 }}>↗</span>
            </button>
          </form>

          {/* Terms/Privacy banner dropped for the self-hosted build —
            real product would link to actual docs. Self-hosted doesn't
            have either. */}

          {/* No bootstrap credential hint — the operator is expected
            to either set AUTH_BOOTSTRAP_USER/PASSWORD in .env, or run
            `POST /api/auth/register` once on an empty DB. */}
        </div>
      </div>

      <style jsx global>{`
        /* Global accent tokens — kept here so any page-level override
         * (e.g. reduced motion) can target the same selector. */
      `}</style>
    </div>
  );
}

const fieldStyle: React.CSSProperties = {
  padding: "11px 14px",
  borderRadius: 10,
  border: "1px solid var(--border)",
  background: "var(--surface-2)",
  fontSize: 14,
  color: "var(--fg)",
  outline: "none",
  transition: "border var(--transition), box-shadow var(--transition)",
};

function ChromeBar({ title }: { title: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "10px 14px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface-2)",
      }}
    >
      <span
        style={{
          width: 12,
          height: 12,
          borderRadius: 999,
          background: "#ef4444",
        }}
      />
      <span
        style={{
          width: 12,
          height: 12,
          borderRadius: 999,
          background: "#eab308",
        }}
      />
      <span
        style={{
          width: 12,
          height: 12,
          borderRadius: 999,
          background: "#22c55e",
        }}
      />
      <div
        style={{
          flex: 1,
          textAlign: "center",
          fontSize: 11,
          color: "var(--fg-muted)",
          fontFamily: '"JetBrains Mono", monospace',
        }}
      >
        {title}
      </div>
    </div>
  );
}

/**
 * Professional group-chat feed: four team-role bots take turns speaking.
 * Each message accumulates like a real transcript, with a "typing…"
 * indicator shown for the next speaker in between. The whole sequence
 * loops. All avatars use one brand accent for a unified, business look.
 */
type ChatMsg = {
  id: string;
  name: string;
  role: string;
  initial: string;
  text: string;
  time: string;
};

const SCRIPT: ChatMsg[] = [
  {
    id: "ba",
    name: "Business Analyst",
    role: "BA",
    initial: "B",
    text: "Scope confirmed — 3 core modules in this iteration.",
    time: "09:41",
  },
  {
    id: "dev",
    name: "Developer",
    role: "Dev",
    initial: "D",
    text: "API design done, submitting for integration today.",
    time: "09:42",
  },
  {
    id: "qa",
    name: "QA Engineer",
    role: "QA",
    initial: "Q",
    text: "Test cases ready, branch coverage at 98%.",
    time: "09:44",
  },
  {
    id: "pm",
    name: "Project Manager",
    role: "PM",
    initial: "P",
    text: "Timeline synced — please track the milestones.",
    time: "09:45",
  },
];

const STEP_MS = 1800; // base interval per state
const TOTAL_STEPS = 8; // 4 shows + 3 typing pauses + 1 full-transcript hold

function AnimatedTerminal() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setStep((s) => (s + 1) % TOTAL_STEPS),
      STEP_MS,
    );
    return () => clearInterval(id);
  }, []);

  // Map the step counter to (visibleCount, typing).
  let visibleCount: number;
  let typing = false;
  if (step <= 6) {
    visibleCount = Math.floor(step / 2) + 1;
    typing = step % 2 === 1;
  } else {
    visibleCount = SCRIPT.length; // step 7: hold the full transcript for a beat
  }

  const visible = SCRIPT.slice(0, visibleCount);
  const nextSpeaker = typing ? SCRIPT[visibleCount] : null;

  return (
    <div
      style={{
        position: "relative",
        padding: "18px 20px",
        flex: 1,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Group header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: "#22c55e",
              boxShadow: "0 0 0 3px rgba(34, 197, 94, 0.15)",
            }}
          />
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>
            Team Collaboration
          </span>
          <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
            · {SCRIPT.length} members
          </span>
        </div>
        <span
          style={{
            fontSize: 11,
            color: "var(--fg-muted)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          In progress
        </span>
      </div>

      {/* Message feed */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {visible.map((m) => (
          <MsgRow key={m.id} msg={m} />
        ))}
        {nextSpeaker && <TypingRow name={nextSpeaker.name} />}
      </div>

      <style jsx>{`
        @keyframes msg-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes dot-blink {
          0%, 60%, 100% { opacity: 0.25; transform: translateY(0); }
          30%           { opacity: 1;    transform: translateY(-2px); }
        }
        .typing-dots { display: inline-flex; gap: 3px; }
        .typing-dots span {
          width: 4px; height: 4px; border-radius: 999px;
          background: var(--fg-muted);
          animation: dot-blink 1.2s infinite;
        }
        .typing-dots span:nth-child(2) { animation-delay: 0.18s; }
        .typing-dots span:nth-child(3) { animation-delay: 0.36s; }
      `}</style>
    </div>
  );
}

/** A single chat message row (avatar + name/role/time + bubble). */
function MsgRow({ msg }: { msg: ChatMsg }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        animation: "msg-in 0.4s ease-out both",
      }}
    >
      <MsgAvatar initial={msg.initial} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginBottom: 4,
          }}
        >
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--fg)" }}>
            {msg.name}
          </span>
          <span style={roleTagStyle}>{msg.role}</span>
          <span
            style={{
              marginLeft: "auto",
              fontSize: 10.5,
              color: "var(--fg-subtle)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {msg.time}
          </span>
        </div>
        <div style={bubbleStyle}>{msg.text}</div>
      </div>
    </div>
  );
}

/** "正在输入…" indicator for the bot about to speak. */
function TypingRow({ name }: { name: string }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        animation: "msg-in 0.4s ease-out both",
      }}
    >
      <MsgAvatar initial="…" />
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontSize: 12.5,
            fontWeight: 600,
            color: "var(--fg)",
            marginBottom: 4,
          }}
        >
          {name}
        </div>
        <div
          style={{
            ...bubbleStyle,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: "var(--fg-muted)",
          }}
        >
          typing…
          <span className="typing-dots">
            <span />
            <span />
            <span />
          </span>
        </div>
      </div>
    </div>
  );
}

/** Brand-accent avatar — one color across all bots for a unified, professional look. */
function MsgAvatar({ initial }: { initial: string }) {
  return (
    <div
      style={{
        width: 34,
        height: 34,
        borderRadius: 9,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg, var(--accent), var(--accent-2))",
        color: "#fff",
        fontSize: 13,
        fontWeight: 600,
        boxShadow: "0 2px 8px rgba(167, 139, 250, 0.28)",
      }}
    >
      {initial}
    </div>
  );
}

const bubbleStyle: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  padding: "9px 12px",
  fontSize: 12.5,
  lineHeight: 1.65,
  color: "var(--fg)",
  boxShadow: "0 1px 3px rgba(15, 23, 42, 0.06)",
};

const roleTagStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 500,
  color: "var(--fg-muted)",
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  borderRadius: 999,
  padding: "1px 7px",
  lineHeight: 1.5,
};
