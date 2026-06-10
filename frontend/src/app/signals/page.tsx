"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";

type HorizonSignal = { horizon_min: number; label: string; confidence: number; reason: string };
type SpySignal = { ts: string; price: number; signals: HorizonSignal[] };
type History = { signals: SpySignal[] };

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
  const [latest, setLatest] = useState<SpySignal | null>(null);
  const [history, setHistory] = useState<SpySignal[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async (): Promise<void> => {
    try {
      const [lRes, hRes] = await Promise.all([
        apiFetch("/signals/spy/latest"),
        apiFetch("/signals/spy/history?limit=30"),
      ]);
      setLatest(lRes.ok ? ((await lRes.json()) as SpySignal) : null);
      setHistory(hRes.ok ? ((await hRes.json()) as History).signals : []);
    } catch {
      setError("Failed to load signals.");
    }
  }, []);

  const runNow = useCallback(async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch("/signals/spy/run", { method: "POST" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? "Run failed");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed.");
    } finally {
      setBusy(false);
    }
  }, [load]);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 30_000); // auto-refresh
    return () => clearInterval(id);
  }, [load]);

  if (authLoading || !user) return <main style={{ background: "#0a0a0a", minHeight: "100vh" }} />;

  return (
    <main
      style={{
        background: "#0a0a0a",
        color: "#f5f5f5",
        minHeight: "100vh",
        padding: "32px 28px",
        fontFamily: "inherit",
        maxWidth: 760,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 6 }}>
        <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em" }}>SPY Signals</h1>
        {latest && (
          <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 18 }}>
            ${latest.price.toFixed(2)}
          </span>
        )}
        <button
          onClick={() => void runNow()}
          disabled={busy}
          style={{
            marginLeft: "auto",
            background: "#e8ff47",
            color: "#0a0a0a",
            border: "none",
            borderRadius: 6,
            padding: "8px 16px",
            fontWeight: 700,
            fontSize: 13,
            cursor: busy ? "default" : "pointer",
            opacity: busy ? 0.6 : 1,
          }}
        >
          {busy ? "Running…" : "Run now"}
        </button>
      </div>

      <p style={{ color: "#555", fontSize: 12, marginBottom: 20 }}>
        Heuristic indicator over recent price action — refreshes every minute. Not a prediction, not
        financial advice.
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
          No signal yet — markets may be closed, or the job hasn’t run. Press “Run now”.
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
                <td colSpan={6} style={{ padding: 14, color: "#555" }}>
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
