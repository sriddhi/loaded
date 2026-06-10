"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";

type HorizonSignal = { horizon_min: number; label: string; confidence: number; reason: string };
type SpySignal = {
  ts: string;
  symbol: string;
  price: number;
  volume: number;
  signals: HorizonSignal[];
};
type History = { signals: SpySignal[] };

const SYMBOLS = ["SPY", "MU", "AVGO"];

const LABEL_COLOR: Record<string, string> = {
  bullish: "#22c55e",
  bearish: "#ef4444",
  bull_trap: "#f59e0b",
  bear_trap: "#47d4ff",
  neutral: "#777",
};

const LABEL_TEXT: Record<string, string> = {
  bullish: "Bullish",
  bearish: "Bearish",
  bull_trap: "Bull trap",
  bear_trap: "Bear trap",
  neutral: "Neutral",
};

const HZ = [5, 10, 20, 1440];

function hzLabel(h: number): string {
  return h >= 1440 ? "1 day" : `${h} min`;
}

function hzShort(h: number): string {
  return h >= 1440 ? "1d" : `${h}m`;
}

function color(label: string): string {
  return LABEL_COLOR[label] ?? "#777";
}

function fmtVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return `${v}`;
}

function Badge({ s }: { s: HorizonSignal }): React.JSX.Element {
  const c = color(s.label);
  return (
    <div
      style={{
        background: "#111",
        border: `1px solid ${c}`,
        borderRadius: 10,
        padding: "16px 18px",
      }}
    >
      <div style={{ color: "#777", fontSize: 12 }}>next {hzLabel(s.horizon_min)}</div>
      <div style={{ color: c, fontSize: 22, fontWeight: 800, marginTop: 6 }}>
        {LABEL_TEXT[s.label] ?? s.label}
      </div>
      <div style={{ color: "#555", fontSize: 11, marginTop: 4 }}>
        confidence {(s.confidence * 100).toFixed(0)}%
      </div>
      {s.reason && (
        <div style={{ color: "#999", fontSize: 11, marginTop: 10, lineHeight: 1.4 }}>
          {s.reason}
        </div>
      )}
    </div>
  );
}

export default function SignalsPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [symbol, setSymbol] = useState<string>("SPY");
  const [latest, setLatest] = useState<SpySignal | null>(null);
  const [history, setHistory] = useState<SpySignal[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async (sym: string): Promise<void> => {
    try {
      const [lRes, hRes] = await Promise.all([
        apiFetch(`/signals/${sym}/latest`),
        apiFetch(`/signals/${sym}/history?limit=30`),
      ]);
      setLatest(lRes.ok ? ((await lRes.json()) as SpySignal) : null);
      setHistory(hRes.ok ? ((await hRes.json()) as History).signals : []);
      setError(null);
    } catch {
      setError("Failed to load signals.");
    }
  }, []);

  useEffect(() => {
    void load(symbol);
    const id = setInterval(() => void load(symbol), 60_000); // auto-refresh every 1 min (matches the job)
    return () => clearInterval(id);
  }, [load, symbol]);

  if (authLoading || !user) return <main style={{ background: "#0a0a0a", minHeight: "100vh" }} />;

  return (
    <main
      style={{
        background: "#0a0a0a",
        color: "#f5f5f5",
        height: "100vh",
        overflowY: "auto",
        padding: "32px 28px",
        fontFamily: "inherit",
        maxWidth: 760,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 6 }}>
        <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em" }}>Signals</h1>
        {latest && (
          <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 18 }}>
            ${latest.price.toFixed(2)}
          </span>
        )}
        {latest && latest.volume > 0 && (
          <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 13, color: "#777" }}>
            vol {fmtVolume(latest.volume)}
          </span>
        )}
      </div>

      {/* Symbol tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        {SYMBOLS.map((sym) => {
          const active = sym === symbol;
          return (
            <button
              key={sym}
              onClick={() => setSymbol(sym)}
              style={{
                background: active ? "#e8ff47" : "#161616",
                color: active ? "#0a0a0a" : "#bbb",
                border: `1px solid ${active ? "#e8ff47" : "#2a2a2a"}`,
                borderRadius: 6,
                padding: "6px 16px",
                fontWeight: 700,
                fontSize: 13,
                letterSpacing: "0.04em",
                cursor: "pointer",
              }}
            >
              {sym}
            </button>
          );
        })}
      </div>

      <p style={{ color: "#555", fontSize: 12, marginBottom: 20 }}>
        Heuristic indicator over recent price action <strong>and volume</strong> — auto-refreshes
        every minute. Not a prediction, not financial advice.
      </p>

      {error && <div style={{ color: "#ef4444", fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {latest ? (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
              gap: 12,
              marginBottom: 8,
            }}
          >
            {latest.signals.map((s) => (
              <Badge key={s.horizon_min} s={s} />
            ))}
          </div>
          <div style={{ color: "#555", fontSize: 11, marginBottom: 28 }}>
            updated {new Date(latest.ts).toLocaleTimeString()}
          </div>
        </>
      ) : (
        <div style={{ color: "#777", fontSize: 14, marginBottom: 28 }}>
          No {symbol} signal yet — markets may be closed, or the job hasn’t run a full cycle.
        </div>
      )}

      {/* History */}
      <h2 style={{ fontSize: 14, color: "#777", fontWeight: 600, marginBottom: 8 }}>Recent</h2>
      <div
        style={{
          background: "#111",
          border: "1px solid #222",
          borderRadius: 10,
          overflow: "hidden",
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 13,
            fontFamily: "var(--font-mono, monospace)",
          }}
        >
          <thead>
            <tr style={{ color: "#777" }}>
              <th style={{ textAlign: "left", padding: "10px 14px" }}>Time</th>
              <th style={{ textAlign: "right", padding: "10px 14px" }}>Price</th>
              <th style={{ textAlign: "right", padding: "10px 14px" }}>Vol</th>
              {HZ.map((h) => (
                <th key={h} style={{ textAlign: "center", padding: "10px 14px" }}>
                  {hzShort(h)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {history.map((row) => (
              <tr key={row.ts} style={{ borderTop: "1px solid #1a1a1a" }}>
                <td style={{ padding: "8px 14px", color: "#aaa" }}>
                  {new Date(row.ts).toLocaleTimeString()}
                </td>
                <td style={{ padding: "8px 14px", textAlign: "right" }}>${row.price.toFixed(2)}</td>
                <td style={{ padding: "8px 14px", textAlign: "right", color: "#888" }}>
                  {fmtVolume(row.volume)}
                </td>
                {row.signals.map((s) => (
                  <td
                    key={s.horizon_min}
                    title={s.reason}
                    style={{
                      padding: "8px 14px",
                      textAlign: "center",
                      color: color(s.label),
                      cursor: s.reason ? "help" : "default",
                    }}
                  >
                    {LABEL_TEXT[s.label] ?? s.label}
                  </td>
                ))}
              </tr>
            ))}
            {history.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: 14, color: "#555" }}>
                  No history yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}
