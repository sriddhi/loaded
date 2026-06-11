"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { Card, PageShell, SectionTitle, Tabs } from "../../components/ui";
import { Sparkline } from "../../components/ui/Chart";
import { color, font, space } from "../../theme/tokens";

type HorizonSignal = {
  horizon_min: number;
  label: string;
  confidence: number;
  reason: string;
  outcome: "pending" | "correct" | "wrong";
};
type SpySignal = {
  ts: string;
  symbol: string;
  price: number;
  volume: number;
  osc: number | null;
  signals: HorizonSignal[];
};
type History = { signals: SpySignal[] };

const SYMBOLS = ["SPY", "MU", "AVGO"];

const LABEL_COLOR: Record<string, string> = {
  bullish: color.up,
  bearish: color.down,
  bull_trap: color.warn,
  bear_trap: color.hue,
  neutral: color.muted,
};
const LABEL_TEXT: Record<string, string> = {
  bullish: "Bullish",
  bearish: "Bearish",
  bull_trap: "Bull trap",
  bear_trap: "Bear trap",
  neutral: "Neutral",
};

const HZ = [1, 5, 10, 20, 1440];
const hzLabel = (h: number): string => (h >= 1440 ? "1 day" : `${h} min`);
const hzShort = (h: number): string => (h >= 1440 ? "1d" : `${h}m`);
const labelColor = (label: string): string => LABEL_COLOR[label] ?? color.muted;

function fmtVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return `${v}`;
}

function OutcomeMark({ outcome }: { outcome: HorizonSignal["outcome"] }): React.JSX.Element {
  if (outcome === "correct")
    return (
      <span style={{ color: color.up, marginLeft: 5 }} title="Backtest: thesis held">
        ✓
      </span>
    );
  if (outcome === "wrong")
    return (
      <span style={{ color: color.down, marginLeft: 5 }} title="Backtest: thesis missed">
        ✗
      </span>
    );
  return (
    <span style={{ color: color.faint, marginLeft: 5 }} title="Backtest: horizon not elapsed yet">
      ·
    </span>
  );
}

type Acc = { hits: number; total: number; confSum: number; confN: number };
function accuracy(history: SpySignal[]): Record<number, Acc> {
  const acc: Record<number, Acc> = {};
  for (const h of HZ) acc[h] = { hits: 0, total: 0, confSum: 0, confN: 0 };
  for (const row of history) {
    for (const s of row.signals) {
      acc[s.horizon_min].confSum += s.confidence;
      acc[s.horizon_min].confN += 1;
      if (s.outcome === "correct" || s.outcome === "wrong") {
        acc[s.horizon_min].total += 1;
        if (s.outcome === "correct") acc[s.horizon_min].hits += 1;
      }
    }
  }
  return acc;
}

function Oscillator({ osc }: { osc: number | null }): React.JSX.Element {
  const zone = osc === null ? "—" : osc <= 30 ? "Oversold" : osc >= 70 ? "Overbought" : "Neutral";
  const zoneColor =
    osc === null ? color.muted : osc <= 30 ? color.up : osc >= 70 ? color.down : color.muted;
  return (
    <Card pad={space[3]} style={{ marginBottom: space[3] }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <span style={{ color: color.muted, fontSize: 11 }}>
          Oscillator (RSI · oversold → overbought)
        </span>
        <span style={{ fontFamily: font.mono, fontSize: 13 }}>
          {osc === null ? "building…" : osc.toFixed(0)}{" "}
          <span style={{ color: zoneColor, fontWeight: 700 }}>{zone}</span>
        </span>
      </div>
      <div
        style={{
          position: "relative",
          height: 8,
          borderRadius: 4,
          background: `linear-gradient(90deg, ${color.up} 0%, ${color.up} 30%, ${color.surface2} 45%, ${color.surface2} 55%, ${color.down} 70%, ${color.down} 100%)`,
          opacity: osc === null ? 0.3 : 1,
        }}
      >
        {osc !== null && (
          <div
            style={{
              position: "absolute",
              left: `calc(${Math.max(0, Math.min(100, osc))}% - 5px)`,
              top: -3,
              width: 10,
              height: 14,
              borderRadius: 3,
              background: color.fg,
              border: `1px solid ${color.bg}`,
            }}
          />
        )}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          color: color.faint,
          fontSize: 9,
          marginTop: 3,
        }}
      >
        <span>0 · oversold</span>
        <span>50</span>
        <span>overbought · 100</span>
      </div>
    </Card>
  );
}

function SignalBadge({ s }: { s: HorizonSignal }): React.JSX.Element {
  const c = labelColor(s.label);
  return (
    <Card hue={c} pad={space[4]}>
      <div style={{ color: color.muted, fontSize: 12 }}>next {hzLabel(s.horizon_min)}</div>
      <div style={{ color: c, fontSize: 22, fontWeight: 800, marginTop: 6 }}>
        {LABEL_TEXT[s.label] ?? s.label}
      </div>
      <div style={{ color: color.faint, fontSize: 11, marginTop: 4 }}>
        confidence {(s.confidence * 100).toFixed(0)}%
      </div>
      {s.reason && (
        <div style={{ color: color.muted, fontSize: 11, marginTop: 10, lineHeight: 1.4 }}>
          {s.reason}
        </div>
      )}
    </Card>
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
        apiFetch(`/signals/${sym}/history?limit=60`),
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
    const id = setInterval(() => void load(symbol), 60_000);
    return () => clearInterval(id);
  }, [load, symbol]);

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  // Price series for the sparkline (oldest → newest).
  const priceSeries = [...history].reverse().map((r) => ({ t: r.ts, v: r.price }));

  return (
    <PageShell
      maxWidth={840}
      title="Signals"
      right={
        latest ? (
          <span style={{ fontFamily: font.mono, fontSize: 16, color: color.fg }}>
            ${latest.price.toFixed(2)}
            {latest.volume > 0 && (
              <span style={{ color: color.muted, fontSize: 13 }}>
                {" "}
                · vol {fmtVolume(latest.volume)}
              </span>
            )}
          </span>
        ) : null
      }
      subtitle="Heuristic indicator over recent price action and volume — auto-refreshes every minute. Not a prediction, not financial advice."
    >
      <div style={{ marginBottom: space[4] }}>
        <Tabs options={SYMBOLS} value={symbol} onChange={setSymbol} />
      </div>

      {error && <div style={{ color: color.down, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {priceSeries.length > 1 && (
        <Card pad={space[3]} style={{ marginBottom: space[3] }}>
          <div style={{ ...labelStyle, marginBottom: 4 }}>
            {symbol} price · last {priceSeries.length} min
          </div>
          <Sparkline data={priceSeries} dataKey="v" height={110} />
        </Card>
      )}

      {latest && <Oscillator osc={latest.osc} />}

      {latest ? (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: space[3],
              marginBottom: space[2],
            }}
          >
            {latest.signals.map((s) => (
              <SignalBadge key={s.horizon_min} s={s} />
            ))}
          </div>
          <div style={{ color: color.faint, fontSize: 11, marginBottom: space[5] }}>
            updated {new Date(latest.ts).toLocaleTimeString()}
          </div>
        </>
      ) : (
        <div style={{ color: color.muted, fontSize: 14, marginBottom: space[5] }}>
          No {symbol} signal yet — markets may be closed, or the job hasn’t run a full cycle.
        </div>
      )}

      <SectionTitle
        right={(() => {
          const acc = accuracy(history);
          const hitParts = HZ.filter((h) => acc[h].total > 0).map(
            (h) =>
              `${hzShort(h)} ${Math.round((acc[h].hits / acc[h].total) * 100)}% (${acc[h].hits}/${acc[h].total})`
          );
          const confParts = HZ.filter((h) => acc[h].confN > 0).map(
            (h) => `${hzShort(h)} ${Math.round((acc[h].confSum / acc[h].confN) * 100)}%`
          );
          return (
            <span style={{ fontSize: 11, color: color.muted, fontFamily: font.mono }}>
              {hitParts.length > 0
                ? `backtest hit-rate · ${hitParts.join("  ·  ")}`
                : "backtest hit-rate · pending"}
              {confParts.length > 0 && (
                <>
                  <span style={{ color: color.faint }}> &nbsp;|&nbsp; </span>
                  avg confidence · {confParts.join("  ·  ")}
                </>
              )}
            </span>
          );
        })()}
      >
        Recent
      </SectionTitle>

      <Card pad={0} style={{ overflow: "hidden" }}>
        <table
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontFamily: font.mono }}
        >
          <thead>
            <tr style={{ color: color.muted }}>
              <th style={{ ...th, textAlign: "left" }}>Time</th>
              <th style={{ ...th, textAlign: "right" }}>Price</th>
              <th style={{ ...th, textAlign: "right" }}>Vol</th>
              {HZ.map((h) => (
                <th key={h} style={{ ...th, textAlign: "center" }}>
                  {hzShort(h)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {history.map((row) => (
              <tr key={row.ts} style={{ borderTop: `1px solid ${color.border}` }}>
                <td style={{ ...td, color: color.muted }}>
                  {new Date(row.ts).toLocaleTimeString()}
                </td>
                <td style={{ ...td, textAlign: "right" }}>${row.price.toFixed(2)}</td>
                <td style={{ ...td, textAlign: "right", color: color.muted }}>
                  {fmtVolume(row.volume)}
                </td>
                {row.signals.map((s) => (
                  <td
                    key={s.horizon_min}
                    title={s.reason}
                    style={{
                      ...td,
                      textAlign: "center",
                      color: labelColor(s.label),
                      cursor: s.reason ? "help" : "default",
                    }}
                  >
                    {LABEL_TEXT[s.label] ?? s.label}
                    <OutcomeMark outcome={s.outcome} />
                  </td>
                ))}
              </tr>
            ))}
            {history.length === 0 && (
              <tr>
                <td colSpan={8} style={{ padding: 14, color: color.faint }}>
                  No history yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}

const labelStyle: React.CSSProperties = { color: color.muted, fontSize: 11 };
const th: React.CSSProperties = { padding: "10px 14px" };
const td: React.CSSProperties = { padding: "8px 14px" };
