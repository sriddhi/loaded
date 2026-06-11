// Design tokens — monochrome + one accent. The single source of truth the UI
// components read from. Mirrors the CSS variables in globals.css so values stay
// in sync; using the JS constants keeps inline styles token-driven and typed.

export const color = {
  bg: "#0e0e0e",
  surface: "#171717",
  surface2: "#1e1e1e",
  border: "#2a2a2a",
  borderStrong: "#383838",

  fg: "#ededed",
  muted: "#8a8a8a",
  faint: "#5c5c5c",

  accent: "#e5e5e5", // near-white primary emphasis
  hue: "#4f9dff", // the one restrained accent hue
  hueDim: "#2f6dbf",

  up: "#46a758",
  down: "#e5484d",
  warn: "#d9a441",
  info: "#4f9dff",
} as const;

// Ordered palette for multi-series charts (monochrome-leaning, accent first).
export const chartPalette = ["#4f9dff", "#ededed", "#8a8a8a", "#46a758", "#e5484d", "#d9a441"];

export const radius = { sm: 6, md: 10, lg: 14 } as const;

export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 24, 6: 32 } as const;

export const font = {
  sans: "var(--font-sans, -apple-system, BlinkMacSystemFont, Inter, sans-serif)",
  mono: 'var(--font-mono, "SF Mono", "Fira Code", monospace)',
} as const;

export const text = {
  h1: { fontSize: 24, fontWeight: 700, letterSpacing: "-0.02em" },
  h2: { fontSize: 15, fontWeight: 600 },
  label: { fontSize: 11, color: color.muted, letterSpacing: "0.02em" },
  body: { fontSize: 14, lineHeight: 1.5 },
  mono: { fontFamily: font.mono, fontSize: 13 },
} as const;

// Mobile breakpoint — pages stack below this. Used via window matchMedia in the
// shared hook so the same components serve desktop + a future mobile build.
export const MOBILE_BREAKPOINT = 720;

// Semantic color for a directional value.
export function trendColor(v: number): string {
  return v > 0 ? color.up : v < 0 ? color.down : color.muted;
}
