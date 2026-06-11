"use client";

import type { CSSProperties, ReactNode } from "react";
import { color, radius, space, text } from "../../theme/tokens";

export { useIsMobile } from "./useIsMobile";

// ── PageShell ─────────────────────────────────────────────────────────────────
// Standard scrollable page frame: full-height, own scroll container (the global
// body is overflow:hidden), responsive horizontal padding + max width.
export function PageShell({
  title,
  subtitle,
  right,
  children,
  maxWidth = 1100,
  pad = true,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  maxWidth?: number;
  pad?: boolean;
}): React.JSX.Element {
  return (
    <main
      style={{
        height: "100vh",
        overflowY: "auto",
        background: color.bg,
        color: color.fg,
        padding: pad ? `clamp(16px, 4vw, ${space[6]}px) clamp(14px, 4vw, ${space[6]}px)` : 0,
      }}
    >
      <div style={{ maxWidth, margin: "0 auto", width: "100%" }}>
        {(title || right) && (
          <header
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: space[4],
              flexWrap: "wrap",
              marginBottom: subtitle ? space[1] : space[4],
            }}
          >
            {title && <h1 style={{ ...text.h1 }}>{title}</h1>}
            {right && <div style={{ marginLeft: "auto" }}>{right}</div>}
          </header>
        )}
        {subtitle && (
          <p style={{ color: color.faint, fontSize: 12, marginBottom: space[5] }}>{subtitle}</p>
        )}
        {children}
      </div>
    </main>
  );
}

// ── Card ──────────────────────────────────────────────────────────────────────
export function Card({
  children,
  style,
  pad = space[4],
  hue,
}: {
  children: ReactNode;
  style?: CSSProperties;
  pad?: number;
  hue?: string;
}): React.JSX.Element {
  return (
    <div
      style={{
        background: color.surface,
        border: `1px solid ${hue ?? color.border}`,
        borderRadius: radius.md,
        padding: pad,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ── SectionTitle ──────────────────────────────────────────────────────────────
export function SectionTitle({
  children,
  right,
}: {
  children: ReactNode;
  right?: ReactNode;
}): React.JSX.Element {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: space[3],
        flexWrap: "wrap",
        marginBottom: space[2],
      }}
    >
      <h2 style={{ ...text.h2, color: color.muted }}>{children}</h2>
      {right}
    </div>
  );
}

// ── Button ────────────────────────────────────────────────────────────────────
type ButtonVariant = "primary" | "ghost" | "danger";
export function Button({
  children,
  onClick,
  variant = "ghost",
  disabled,
  active,
  style,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  active?: boolean;
  style?: CSSProperties;
  title?: string;
}): React.JSX.Element {
  const base: CSSProperties = {
    border: `1px solid ${color.border}`,
    borderRadius: radius.sm,
    padding: "6px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.55 : 1,
    fontFamily: "inherit",
    transition: "background .12s, border-color .12s",
  };
  const variants: Record<ButtonVariant, CSSProperties> = {
    primary: { background: color.accent, color: color.bg, borderColor: color.accent },
    ghost: {
      background: active ? color.surface2 : "transparent",
      color: active ? color.fg : color.muted,
      borderColor: active ? color.borderStrong : color.border,
    },
    danger: { background: "transparent", color: color.down, borderColor: color.border },
  };
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      style={{ ...base, ...variants[variant], ...style }}
    >
      {children}
    </button>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────────
export function Badge({
  children,
  tone = color.muted,
  filled,
}: {
  children: ReactNode;
  tone?: string;
  filled?: boolean;
}): React.JSX.Element {
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        padding: "2px 7px",
        borderRadius: radius.sm,
        border: `1px solid ${tone}`,
        color: filled ? color.bg : tone,
        background: filled ? tone : "transparent",
      }}
    >
      {children}
    </span>
  );
}

// ── Stat ──────────────────────────────────────────────────────────────────────
export function Stat({
  label,
  value,
  tone,
  sub,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: string;
  sub?: ReactNode;
}): React.JSX.Element {
  return (
    <div>
      <div style={{ ...text.label }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4, color: tone ?? color.fg }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: color.faint, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
export function Tabs({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
}): React.JSX.Element {
  return (
    <div style={{ display: "flex", gap: space[2], flexWrap: "wrap" }}>
      {options.map((o) => (
        <Button key={o} variant="ghost" active={o === value} onClick={() => onChange(o)}>
          {o}
        </Button>
      ))}
    </div>
  );
}
