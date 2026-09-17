"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui";
import { api, User } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/**
 * 4SAPI-style login window. The left panel is now an *animated* terminal:
 * a live typing cursor + sequential frames that mimic a real API call
 * (curl request → thinking spinner → 200 OK). The right panel is the
 * simplified sign-in form (no OAuth).
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
        {/* Left: animated terminal */}
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
          <ChromeBar title="auth@botgroup: ~/login" />
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
              placeholder="admin"
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
              placeholder="••••••••"
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

          <div
            style={{
              fontSize: 11,
              color: "var(--fg-subtle)",
              textAlign: "center",
              lineHeight: 1.5,
              marginTop: 4,
            }}
          >
            {t("login.termsHint")}
            <a
              href="#"
              onClick={(e) => e.preventDefault()}
              style={{ color: "var(--fg-muted)", marginLeft: 4 }}
            >
              {t("login.terms")}
            </a>
            <span style={{ margin: "0 6px" }}>·</span>
            <a
              href="#"
              onClick={(e) => e.preventDefault()}
              style={{ color: "var(--fg-muted)" }}
            >
              {t("login.privacy")}
            </a>
          </div>

          <div
            style={{
              fontSize: 11,
              color: "var(--fg-subtle)",
              borderTop: "1px solid var(--border)",
              paddingTop: 12,
              lineHeight: 1.55,
            }}
          >
            {t("login.bootstrapHint")}
          </div>
        </div>
      </div>

      <style jsx global>{`
        @keyframes blink {
          0%, 49% { opacity: 1; }
          50%, 100% { opacity: 0; }
        }
        @keyframes progress {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(400%); }
        }
        @keyframes dots {
          0%, 20% { content: ''; }
          40% { content: '.'; }
          60% { content: '..'; }
          80%, 100% { content: '...'; }
        }
        .cursor-blink::after {
          content: '▍';
          display: inline-block;
          color: var(--accent);
          margin-left: 2px;
          animation: blink 1s steps(1) infinite;
          font-weight: 400;
        }
        .loading-dots::after {
          content: '...';
          animation: dots 1.4s steps(1) infinite;
        }
        .progress-bar {
          position: relative;
          height: 2px;
          background: rgba(167, 139, 250, 0.15);
          border-radius: 2px;
          overflow: hidden;
        }
        .progress-bar::before {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          width: 25%;
          height: 100%;
          background: linear-gradient(90deg, transparent, var(--accent), transparent);
          animation: progress 1.6s linear infinite;
        }
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
 * Animated terminal — drives a multi-stage "story":
 *  1. Idle prompt
 *  2. User types the curl command (typewriter)
 *  3. Request body is sent (typing…)
 *  4. Thinking/progress spinner + status bar
 *  5. 200 OK with the JSON response
 * Then loops back with the same or a similar demo.
 *
 * No GIF needed — pure CSS keyframes + state machine.
 */
function AnimatedTerminal() {
  const STAGES = [
    { delay: 600, kind: "prompt" as const },
    { delay: 900, kind: "request" as const },
    { delay: 600, kind: "headers" as const },
    { delay: 400, kind: "blank" as const },
    { delay: 1200, kind: "thinking" as const },
    { delay: 600, kind: "response" as const },
    { delay: 2400, kind: "loop" as const },
  ];
  const TOTAL = STAGES.reduce((a, s) => a + s.delay, 0);

  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => (t + 1) % TOTAL), 100);
    return () => clearInterval(id);
  }, [TOTAL]);

  // Calculate which stage we're in based on tick.
  let acc = 0;
  let stageIdx = 0;
  let stageProgress = 0;
  for (let i = 0; i < STAGES.length; i++) {
    if (tick < acc + STAGES[i].delay) {
      stageIdx = i;
      stageProgress = (tick - acc) / STAGES[i].delay;
      break;
    }
    acc += STAGES[i].delay;
  }

  // The typed characters grow over the stage window.
  const stage = STAGES[stageIdx];

  return (
    <div
      style={{
        position: "relative",
        padding: "20px 22px",
        fontFamily: '"JetBrains Mono", ui-monospace, monospace',
        fontSize: 12.5,
        lineHeight: 1.7,
        color: "var(--fg)",
        flex: 1,
        overflow: "hidden",
      }}
    >
      {/* Persistent prompt row */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>$</span>
        <TypedText
          target={"curl -X POST /api/auth/login"}
          progress={stageIdx > 0 ? 1 : stageProgress}
          cursorVisible={stageIdx === 0}
        />
      </div>

      {stageIdx >= 1 && (
        <div
          style={{
            color: "var(--fg-muted)",
            marginLeft: 16,
            animation: "fade-in 0.2s",
          }}
        >
          {"> "}H{"\u00A0"}<TypedText
            target={"Content-Type: application/json"}
            progress={stageIdx > 1 ? 1 : stageProgress}
          />
        </div>
      )}
      {stageIdx >= 2 && (
        <div
          style={{
            color: "var(--fg-muted)",
            marginLeft: 16,
            animation: "fade-in 0.2s",
          }}
        >
          {"> "}{"{"}"username{": \"admin\""}
        </div>
      )}
      {stageIdx >= 3 && (
        <div
          style={{
            color: "var(--fg-muted)",
            marginLeft: 16,
            animation: "fade-in 0.2s",
          }}
        >
          {"\u00A0".repeat(11)}password{": \"••••••\""}
        </div>
      )}

      {/* Thinking indicator */}
      {stageIdx === 4 && (
        <div
          style={{
            marginTop: 12,
            animation: "fade-in 0.2s",
            color: "var(--fg-muted)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "var(--accent)" }}>→</span>
            <span>
              authenticating<span className="loading-dots" />
            </span>
          </div>
          <div style={{ marginTop: 8 }}>
            <div className="progress-bar" />
          </div>
        </div>
      )}

      {/* Response */}
      {stageIdx >= 5 && (
        <div style={{ marginTop: 14, animation: "fade-in 0.3s" }}>
          <div>
            <span style={{ color: "#22c55e", fontWeight: 600 }}>
              ← 200 OK
            </span>{" "}
            <span style={{ color: "var(--fg-subtle)" }}>12 ms</span>
          </div>
          <div style={{ color: "var(--fg-muted)", marginTop: 4 }}>
            {"{"}"id": 1, "username":{" "}
            <span style={{ color: "var(--accent)" }}>"admin"</span>, "token":
            eyJhbGciOiJIUzI1NiI...
            {"}"}
          </div>
          <div
            style={{
              marginTop: 12,
              color: "var(--fg-subtle)",
              fontStyle: "italic",
            }}
          >
            # session cookie stored · redirecting →
          </div>
        </div>
      )}

      <style jsx>{`
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(2px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

function TypedText({
  target,
  progress,
  cursorVisible,
}: {
  target: string;
  progress: number; // 0..1
  cursorVisible?: boolean;
}) {
  const chars = Math.floor(progress * target.length);
  const text = target.slice(0, chars);
  return (
    <span>
      <span style={{ color: "#a78bfa" }}>{text || "\u00A0"}</span>
      {cursorVisible && <span className="cursor-blink" />}
    </span>
  );
}