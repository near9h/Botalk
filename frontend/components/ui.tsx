"use client";
/**
 * BotGroup UI primitives — shadcn/ui inspired, copy-paste, zero npm deps.
 *
 * Exports: Button, Input, Textarea, Label, Card, Dialog, Select, Tabs, Slider,
 * Badge, Avatar, EmptyState, Toast, IconButton.
 */
import {
  CSSProperties,
  KeyboardEvent,
  ReactNode,
  Ref,
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

/* ──────────────────────────── utils ──────────────────────────── */

export function cn(...args: Array<string | false | null | undefined>): string {
  return args.filter(Boolean).join(" ");
}

export type CssVars = Record<string, string | number>;
export function cssVars(vars: CssVars): CSSProperties {
  return vars as CSSProperties;
}

/* ──────────────────────────── Button ──────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type ButtonSize = "sm" | "md" | "lg" | "icon";

const buttonVariantStyles: Record<ButtonVariant, CSSProperties> = {
  primary: {
    background: "linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%)",
    color: "white",
    boxShadow: "0 1px 0 rgba(255,255,255,0.4) inset, 0 4px 14px rgba(139, 92, 246, 0.30)",
  },
  secondary: {
    background: "var(--surface-2)",
    color: "var(--fg)",
    border: "1px solid var(--border)",
    boxShadow: "var(--shadow-xs)",
  },
  ghost: {
    background: "transparent",
    color: "var(--fg)",
  },
  outline: {
    background: "transparent",
    color: "var(--fg)",
    border: "1px solid var(--border-strong)",
  },
  danger: {
    background: "var(--danger-bg)",
    color: "#991B1B",
    border: "1px solid #FCA5A5",
  },
};

const buttonSizeStyles: Record<ButtonSize, CSSProperties> = {
  sm: { height: 28, padding: "0 10px", fontSize: 12, borderRadius: "var(--radius-sm)" },
  md: { height: 36, padding: "0 14px", fontSize: 13, borderRadius: "var(--radius)" },
  lg: { height: 44, padding: "0 20px", fontSize: 14, borderRadius: "var(--radius)" },
  icon: {
    height: 36,
    width: 36,
    padding: 0,
    borderRadius: "var(--radius)",
    fontSize: 16,
  },
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", style, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        fontWeight: 500,
        whiteSpace: "nowrap",
        transition: "transform var(--transition), background var(--transition), box-shadow var(--transition)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
        ...buttonVariantStyles[variant],
        ...buttonSizeStyles[size],
        ...style,
      }}
      onMouseDown={(e) => {
        if (!disabled) (e.currentTarget as HTMLButtonElement).style.transform = "scale(0.97)";
      }}
      onMouseUp={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)";
      }}
      {...rest}
    >
      {children}
    </button>
  );
});

export const IconButton = forwardRef<HTMLButtonElement, Omit<ButtonProps, "size">>(function IconButton(
  props,
  ref,
) {
  return <Button ref={ref} size="icon" variant="ghost" {...props} />;
});

/* ──────────────────────────── Input ──────────────────────────── */

const inputBaseStyle: CSSProperties = {
  width: "100%",
  height: 36,
  padding: "0 12px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--border-strong)",
  background: "var(--surface-solid)",
  color: "var(--fg)",
  fontSize: 13,
  transition: "border var(--transition), box-shadow var(--transition)",
  outline: "none",
};

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ style, ...rest }, ref) {
    return (
      <input
        ref={ref}
        style={{ ...inputBaseStyle, ...style }}
        onFocus={(e) => {
          (e.currentTarget as HTMLInputElement).style.borderColor = "var(--accent)";
          (e.currentTarget as HTMLInputElement).style.boxShadow =
            "0 0 0 3px rgba(167, 139, 250, 0.15)";
          rest.onFocus?.(e);
        }}
        onBlur={(e) => {
          (e.currentTarget as HTMLInputElement).style.borderColor = "var(--border-strong)";
          (e.currentTarget as HTMLInputElement).style.boxShadow = "none";
          rest.onBlur?.(e);
        }}
        {...rest}
      />
    );
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ style, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        style={{
          ...inputBaseStyle,
          height: "auto",
          minHeight: 80,
          padding: "10px 12px",
          fontFamily: "inherit",
          lineHeight: 1.5,
          ...style,
        }}
        onFocus={(e) => {
          (e.currentTarget as HTMLTextAreaElement).style.borderColor = "var(--accent)";
          (e.currentTarget as HTMLTextAreaElement).style.boxShadow =
            "0 0 0 3px rgba(167, 139, 250, 0.15)";
          rest.onFocus?.(e);
        }}
        onBlur={(e) => {
          (e.currentTarget as HTMLTextAreaElement).style.borderColor = "var(--border-strong)";
          (e.currentTarget as HTMLTextAreaElement).style.boxShadow = "none";
          rest.onBlur?.(e);
        }}
        {...rest}
      />
    );
  },
);

export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label
      htmlFor={htmlFor}
      style={{
        display: "block",
        fontSize: 12,
        fontWeight: 500,
        color: "var(--fg-muted)",
        marginBottom: 6,
        letterSpacing: 0.2,
        textTransform: "uppercase",
      }}
    >
      {children}
    </label>
  );
}

/* ──────────────────────────── Card ──────────────────────────── */

export function Card({
  children,
  style,
  className,
  onClick,
  hoverable = false,
}: {
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
  onClick?: () => void;
  hoverable?: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      className={cn("glass animate-fade-in", className)}
      onClick={onClick}
      onMouseEnter={() => hoverable && setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: 20,
        cursor: onClick || hoverable ? "pointer" : "default",
        transition: "transform var(--transition), box-shadow var(--transition)",
        transform: hover ? "translateY(-2px)" : "translateY(0)",
        boxShadow: hover ? "var(--shadow-lg)" : "var(--shadow)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/* ──────────────────────────── Dialog ──────────────────────────── */

interface DialogContextValue {
  open: boolean;
  setOpen: (v: boolean) => void;
}
const DialogContext = createContext<DialogContextValue | null>(null);

export function Dialog({
  open,
  onOpenChange,
  children,
  maxWidth = 560,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  children: ReactNode;
  maxWidth?: number;
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    const onClose = () => onOpenChange(false);
    el.addEventListener("close", onClose);
    return () => el.removeEventListener("close", onClose);
  }, [onOpenChange]);

  // Close on backdrop click.
  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    const handleClick = (e: MouseEvent) => {
      if (e.target === el) onOpenChange(false);
    };
    el.addEventListener("click", handleClick);
    return () => el.removeEventListener("click", handleClick);
  }, [onOpenChange]);

  return (
    <DialogContext.Provider value={{ open, setOpen: onOpenChange }}>
      <dialog
        ref={dialogRef}
        style={{
          padding: 0,
          border: "none",
          background: "transparent",
          maxWidth: "none",
          maxHeight: "none",
          inset: 0,
          width: "100vw",
          height: "100vh",
        }}
      >
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.32)",
            backdropFilter: "blur(8px)",
          }}
        />
        <div
          style={{
            position: "fixed",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
        >
          <div
            className="glass-strong animate-scale-in"
            style={{
              position: "relative",
              maxWidth,
              width: "100%",
              maxHeight: "calc(100vh - 48px)",
              overflow: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {children}
          </div>
        </div>
      </dialog>
    </DialogContext.Provider>
  );
}

export function DialogContent({ children }: { children: ReactNode }) {
  return <div style={{ padding: 24 }}>{children}</div>;
}

export function DialogHeader({ title, description, onClose }: { title: string; description?: string; onClose?: () => void }) {
  const ctx = useContext(DialogContext);
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>{title}</h2>
        {description && (
          <p style={{ fontSize: 13, color: "var(--fg-muted)" }}>{description}</p>
        )}
      </div>
      {onClose && ctx && (
        <IconButton onClick={() => ctx.setOpen(false)} aria-label="Close">
          ✕
        </IconButton>
      )}
    </div>
  );
}

export function DialogFooter({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "flex-end",
        gap: 8,
        marginTop: 20,
        paddingTop: 16,
        borderTop: "1px solid var(--border)",
      }}
    >
      {children}
    </div>
  );
}

/* ──────────────────────────── Custom Select ──────────────────────────── */

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
  badge?: ReactNode;
  icon?: ReactNode;
}

export function Select({
  value,
  onChange,
  options,
  placeholder = "选择…",
  searchable = false,
  fullWidth = true,
}: {
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  searchable?: boolean;
  fullWidth?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const selected = options.find((o) => o.value === value);
  const filtered = useMemo(() => {
    if (!query) return options;
    const q = query.toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q));
  }, [options, query]);

  return (
    <div ref={ref} style={{ position: "relative", width: fullWidth ? "100%" : "auto" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          ...inputBaseStyle,
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          textAlign: "left",
          height: 36,
          padding: "0 12px",
          cursor: "pointer",
        }}
      >
        {selected ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            {selected.icon}
            <span>{selected.label}</span>
            {selected.badge}
          </span>
        ) : (
          <span style={{ color: "var(--fg-subtle)" }}>{placeholder}</span>
        )}
        <span style={{ color: "var(--fg-muted)", fontSize: 10 }}>▾</span>
      </button>

      {open && (
        <div
          className="glass-strong animate-scale-in"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            right: 0,
            zIndex: 50,
            padding: 6,
            maxHeight: 320,
            overflow: "auto",
          }}
        >
          {searchable && (
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索模型…"
              style={{
                ...inputBaseStyle,
                width: "100%",
                marginBottom: 6,
              }}
            />
          )}
          {filtered.length === 0 ? (
            <div style={{ padding: 12, color: "var(--fg-subtle)", fontSize: 12, textAlign: "center" }}>
              无匹配项
            </div>
          ) : (
            filtered.map((o) => (
              <button
                key={o.value}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                  setQuery("");
                }}
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  borderRadius: "var(--radius-sm)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                  background: value === o.value ? "rgba(167, 139, 250, 0.10)" : "transparent",
                  color: "var(--fg)",
                  transition: "background var(--transition)",
                  textAlign: "left",
                }}
                onMouseEnter={(e) => {
                  if (value !== o.value) (e.currentTarget as HTMLButtonElement).style.background = "rgba(15, 23, 42, 0.04)";
                }}
                onMouseLeave={(e) => {
                  if (value !== o.value) (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                }}
              >
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                  {o.icon}
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {o.label}
                  </span>
                </span>
                {o.badge}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* ──────────────────────────── Tabs ──────────────────────────── */

export interface TabItem {
  value: string;
  label: string;
  icon?: ReactNode;
}

export function Tabs({
  items,
  value,
  onChange,
}: {
  items: TabItem[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div
      className="glass"
      style={{
        display: "inline-flex",
        padding: 4,
        gap: 2,
        borderRadius: "var(--radius)",
      }}
    >
      {items.map((t) => {
        const active = value === t.value;
        return (
          <button
            key={t.value}
            onClick={() => onChange(t.value)}
            style={{
              padding: "6px 14px",
              borderRadius: "var(--radius-sm)",
              fontSize: 13,
              fontWeight: 500,
              color: active ? "var(--fg)" : "var(--fg-muted)",
              background: active ? "var(--surface-solid)" : "transparent",
              boxShadow: active ? "var(--shadow-xs)" : "none",
              transition: "all var(--transition)",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {t.icon}
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/* ──────────────────────────── Slider ──────────────────────────── */

export function Slider({
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.1,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, width: "100%" }}>
      <div style={{ flex: 1, position: "relative", height: 24, display: "flex", alignItems: "center" }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            height: 6,
            borderRadius: 999,
            background: "var(--border-strong)",
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 0,
            width: `${pct}%`,
            height: 6,
            borderRadius: 999,
            background: "linear-gradient(90deg, var(--accent-2), var(--accent))",
          }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          style={{
            position: "absolute",
            inset: 0,
            opacity: 0,
            cursor: "pointer",
            width: "100%",
            height: "100%",
          }}
        />
        <div
          style={{
            position: "absolute",
            left: `calc(${pct}% - 7px)`,
            width: 14,
            height: 14,
            borderRadius: 999,
            background: "white",
            border: "2px solid var(--accent)",
            boxShadow: "0 2px 6px rgba(0,0,0,0.10)",
            pointerEvents: "none",
          }}
        />
      </div>
      <span
        style={{
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: 12,
          color: "var(--fg-muted)",
          minWidth: 36,
          textAlign: "right",
        }}
      >
        {value.toFixed(1)}
      </span>
    </div>
  );
}

/* ──────────────────────────── Badge ──────────────────────────── */

type BadgeVariant = "default" | "openai" | "anthropic" | "google" | "zhipu" | "alibaba" | "deepseek" | "bytedance" | "moonshot" | "baidu" | "minimax" | "other" | "auto" | "manual" | "round_robin" | "info" | "success" | "warning";

const badgeVariantStyles: Record<BadgeVariant, CSSProperties> = {
  default: { background: "var(--surface-2)", color: "var(--fg-muted)", border: "1px solid var(--border)" },
  openai: { background: "rgba(16, 185, 129, 0.12)", color: "var(--vendor-openai)" },
  anthropic: { background: "rgba(217, 119, 6, 0.12)", color: "var(--vendor-anthropic)" },
  google: { background: "rgba(66, 133, 244, 0.12)", color: "var(--vendor-google)" },
  zhipu: { background: "rgba(99, 102, 241, 0.12)", color: "var(--vendor-zhipu)" },
  alibaba: { background: "rgba(255, 106, 0, 0.12)", color: "var(--vendor-alibaba)" },
  deepseek: { background: "rgba(30, 64, 175, 0.12)", color: "var(--vendor-deepseek)" },
  bytedance: { background: "rgba(37, 99, 235, 0.12)", color: "var(--vendor-bytedance)" },
  moonshot: { background: "rgba(14, 165, 233, 0.12)", color: "var(--vendor-moonshot)" },
  baidu: { background: "rgba(220, 38, 38, 0.12)", color: "var(--vendor-baidu)" },
  minimax: { background: "rgba(219, 39, 119, 0.12)", color: "var(--vendor-minimax)" },
  other: { background: "rgba(107, 114, 128, 0.12)", color: "var(--vendor-other)" },
  auto: { background: "rgba(167, 139, 250, 0.15)", color: "var(--accent)" },
  manual: { background: "rgba(252, 211, 77, 0.20)", color: "#92400E" },
  round_robin: { background: "rgba(134, 239, 172, 0.20)", color: "#065F46" },
  info: { background: "rgba(147, 197, 253, 0.20)", color: "#1E40AF" },
  success: { background: "rgba(134, 239, 172, 0.20)", color: "#065F46" },
  warning: { background: "rgba(252, 211, 77, 0.20)", color: "#92400E" },
};

export function Badge({
  children,
  variant = "default",
  style,
}: {
  children: ReactNode;
  variant?: BadgeVariant;
  style?: CSSProperties;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: "var(--radius-full)",
        fontSize: 11,
        fontWeight: 500,
        lineHeight: 1.5,
        ...badgeVariantStyles[variant],
        ...style,
      }}
    >
      {children}
    </span>
  );
}

export function vendorBadgeVariant(vendor: string): BadgeVariant {
  const v = vendor.toLowerCase();
  if (v in badgeVariantStyles) return v as BadgeVariant;
  return "other";
}

/* ──────────────────────────── Avatar ──────────────────────────── */

export function Avatar({
  emoji,
  size = 40,
  color,
  ring = false,
}: {
  emoji: string;
  size?: number;
  color?: string;
  ring?: boolean;
}) {
  const bg = color ?? "linear-gradient(135deg, #FDE68A, #FCA5A5)";
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        background: bg,
        fontSize: size * 0.55,
        flexShrink: 0,
        boxShadow: ring ? "0 0 0 3px rgba(167, 139, 250, 0.30)" : "var(--shadow-xs)",
        userSelect: "none",
      }}
    >
      <span style={{ lineHeight: 1 }}>{emoji}</span>
    </div>
  );
}

const palette = [
  "linear-gradient(135deg, #FDE68A, #FCA5A5)",
  "linear-gradient(135deg, #BFDBFE, #C4B5FD)",
  "linear-gradient(135deg, #BBF7D0, #86EFAC)",
  "linear-gradient(135deg, #FED7AA, #FCA5A5)",
  "linear-gradient(135deg, #DDD6FE, #FBCFE8)",
  "linear-gradient(135deg, #A7F3D0, #6EE7B7)",
  "linear-gradient(135deg, #FECACA, #FCA5A5)",
  "linear-gradient(135deg, #C7D2FE, #A5B4FC)",
];

export function avatarColor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return palette[Math.abs(h) % palette.length];
}

/* ──────────────────────────── EmptyState ──────────────────────────── */

export function EmptyState({
  emoji,
  title,
  description,
  action,
}: {
  emoji?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div
      className="glass animate-slide-up"
      style={{
        padding: 40,
        textAlign: "center",
        maxWidth: 420,
        margin: "40px auto",
      }}
    >
      {emoji && (
        <div style={{ fontSize: 56, marginBottom: 12, lineHeight: 1 }}>{emoji}</div>
      )}
      <h3 style={{ fontSize: 16, marginBottom: 6 }}>{title}</h3>
      {description && (
        <p style={{ fontSize: 13, color: "var(--fg-muted)", marginBottom: 16, lineHeight: 1.6 }}>
          {description}
        </p>
      )}
      {action}
    </div>
  );
}

/* ──────────────────────────── Toast ──────────────────────────── */

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  variant?: "default" | "success" | "error" | "info";
}
interface ToastContextValue {
  push: (t: Omit<ToastItem, "id">) => void;
}
const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((t: Omit<ToastItem, "id">) => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, ...t }]);
    setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== id)), 3200);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div
        style={{
          position: "fixed",
          top: 20,
          right: 20,
          zIndex: 100,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          maxWidth: 360,
        }}
      >
        {items.map((t) => {
          const accent =
            t.variant === "error"
              ? "var(--danger)"
              : t.variant === "success"
              ? "var(--accent-3)"
              : t.variant === "info"
              ? "var(--accent-2)"
              : "var(--accent)";
          return (
            <div
              key={t.id}
              className="glass-strong animate-slide-up"
              style={{
                padding: 12,
                borderLeft: `3px solid ${accent}`,
                borderRadius: "var(--radius)",
              }}
            >
              <div style={{ fontWeight: 500, fontSize: 13, marginBottom: t.description ? 4 : 0 }}>
                {t.title}
              </div>
              {t.description && (
                <div style={{ fontSize: 12, color: "var(--fg-muted)" }}>{t.description}</div>
              )}
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be inside ToastProvider");
  return ctx;
}

/* ──────────────────────────── re-exports ──────────────────────────── */
export { useState, useEffect, useRef, forwardRef, useContext, useMemo, useCallback, createContext, useId };