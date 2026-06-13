"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { Button, Card, InfoTip, PageShell, SectionTitle, useIsMobile } from "../../components/ui";
import { PriceVolumeChart, Sparkline } from "../../components/ui/Chart";
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

const SYMBOLS = ["SPY", "MU", "AVGO", "MSFT", "IBM", "INTC"];

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

const TIP = {
  oscillator:
    "RSI-style 0–100 oscillator. Below 30 = oversold (price fell hard and fast), above 70 = overbought (rose hard and fast). Extremes often precede a pause or reversal — not a guarantee.",
  horizons:
    "Each chip is the heuristic's read for the next 1m/5m/10m/20m/1day. ✓/✗ marks whether past calls held up once the horizon elapsed (backtest).",
  bullTrap:
    "Bull trap = price pushing up on weak volume — a rally that may not hold. Bear trap = a weak-volume dip that may snap back.",
};

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

function MiniOsc({ osc }: { osc: number | null }): React.JSX.Element {
  return (
    <div
      style={{
        position: "relative",
        height: 5,
        borderRadius: 3,
        background: `linear-gradient(90deg, ${color.up} 0%, ${color.up} 30%, ${color.surface2} 45%, ${color.surface2} 55%, ${color.down} 70%, ${color.down} 100%)`,
        opacity: osc === null ? 0.25 : 1,
      }}
    >
      {osc !== null && (
        <div
          style={{
            position: "absolute",
            left: `calc(${Math.max(0, Math.min(100, osc))}% - 4px)`,
            top: -2,
            width: 8,
            height: 9,
            borderRadius: 2,
            background: color.fg,
            border: `1px solid ${color.bg}`,
          }}
        />
      )}
    </div>
  );
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
        <InfoTip text={TIP.oscillator}>
          <span
            style={{
              color: color.muted,
              fontSize: 11,
              borderBottom: `1px dotted ${color.faint}`,
            }}
          >
            Oscillator (RSI · oversold → overbought)
          </span>
        </InfoTip>
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

// ── Symbol tile (the grid view) ───────────────────────────────────────────────

function SymbolTile({
  data,
  spark,
  onOpen,
}: {
  data: SpySignal | null;
  spark: { t: string; v: number }[];
  onOpen: () => void;
}): React.JSX.Element {
  const sig5 = data?.signals.find((s) => s.horizon_min === 5);
  const sig1d = data?.signals.find((s) => s.horizon_min === 1440);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onOpen();
      }}
      style={{ cursor: "pointer", outlineColor: color.hue }}
    >
      <Card pad={space[3]}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span style={{ fontWeight: 800, fontSize: 15 }}>{data?.symbol ?? "…"}</span>
          <span style={{ fontFamily: font.mono, fontSize: 14 }}>
            {data ? `$${data.price.toFixed(2)}` : "—"}
          </span>
        </div>
        <div
          style={{
            color: color.muted,
            fontSize: 10,
            fontFamily: font.mono,
            display: "flex",
            justifyContent: "space-between",
            marginTop: 2,
          }}
        >
          <span>vol {data && data.volume > 0 ? fmtVolume(data.volume) : "—"}</span>
          <span>
            RSI{" "}
            <span
              style={{
                color:
                  data?.osc == null
                    ? color.faint
                    : data.osc <= 30
                      ? color.up
                      : data.osc >= 70
                        ? color.down
                        : color.muted,
                fontWeight: 700,
              }}
            >
              {data?.osc == null ? "—" : data.osc.toFixed(0)}
            </span>
          </span>
        </div>
        <div style={{ margin: "8px 0 6px" }}>
          {spark.length > 1 ? (
            <Sparkline data={spark} dataKey="v" height={44} />
          ) : (
            <div
              style={{
                height: 44,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: color.faint,
                fontSize: 10,
              }}
            >
              no recent ticks
            </div>
          )}
        </div>
        <div style={{ margin: "6px 0" }}>
          <MiniOsc osc={data?.osc ?? null} />
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
          {sig5 && (
            <span style={{ fontSize: 10, color: labelColor(sig5.label), fontWeight: 700 }}>
              5m {LABEL_TEXT[sig5.label] ?? sig5.label}
            </span>
          )}
          {sig1d && (
            <span style={{ fontSize: 10, color: labelColor(sig1d.label), fontWeight: 700 }}>
              1d {LABEL_TEXT[sig1d.label] ?? sig1d.label}
            </span>
          )}
          <span style={{ fontSize: 10, color: color.faint, marginLeft: "auto" }}>history →</span>
        </div>
      </Card>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SignalsPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const isMobile = useIsMobile();
  const [selected, setSelected] = useState<string | null>(null);
  const [latestBySym, setLatestBySym] = useState<Record<string, SpySignal | null>>({});
  const [historyBySym, setHistoryBySym] = useState<Record<string, SpySignal[]>>({});
  const [detailHistory, setDetailHistory] = useState<SpySignal[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const loadGrid = useCallback(async (): Promise<void> => {
    try {
      const results = await Promise.all(
        SYMBOLS.map(async (sym) => {
          const [lRes, hRes] = await Promise.all([
            apiFetch(`/signals/${sym}/latest`),
            apiFetch(`/signals/${sym}/history?limit=30`),
          ]);
          return {
            sym,
            latest: lRes.ok ? ((await lRes.json()) as SpySignal) : null,
            history: hRes.ok ? ((await hRes.json()) as History).signals : [],
          };
        })
      );
      setLatestBySym(Object.fromEntries(results.map((r) => [r.sym, r.latest])));
      setHistoryBySym(Object.fromEntries(results.map((r) => [r.sym, r.history])));
      setError(null);
    } catch {
      setError("Failed to load signals.");
    }
  }, []);

  const loadDetail = useCallback(async (sym: string): Promise<void> => {
    try {
      const hRes = await apiFetch(`/signals/${sym}/history?limit=60`);
      setDetailHistory(hRes.ok ? ((await hRes.json()) as History).signals : []);
    } catch {
      setDetailHistory([]);
    }
  }, []);

  useEffect(() => {
    void loadGrid();
    const id = setInterval(() => void loadGrid(), 60_000);
    return () => clearInterval(id);
  }, [loadGrid]);

  useEffect(() => {
    if (!selected) return;
    void loadDetail(selected);
    const id = setInterval(() => void loadDetail(selected), 60_000);
    return () => clearInterval(id);
  }, [selected, loadDetail]);

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  const latest = selected ? latestBySym[selected] : null;
  // Oldest → newest rows for the price+volume chart.
  const chartRows = [...detailHistory].reverse().map((r) => ({
    x: new Date(r.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    price: r.price,
    volume: r.volume,
  }));

  return (
    <PageShell
      maxWidth={1100}
      title="Signals"
      right={
        selected && latest ? (
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
      {error && <div style={{ color: color.down, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {!selected ? (
        // ── Tile grid: one card per symbol; click for history ──────────────────
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)",
            gap: space[3],
          }}
        >
          {SYMBOLS.map((sym) => (
            <SymbolTile
              key={sym}
              data={latestBySym[sym] ?? null}
              spark={[...(historyBySym[sym] ?? [])].reverse().map((r) => ({ t: r.ts, v: r.price }))}
              onOpen={() => setSelected(sym)}
            />
          ))}
        </div>
      ) : (
        // ── Detail: price+volume chart, oscillator, horizon chips, history ─────
        <>
          <div style={{ marginBottom: space[3] }}>
            <Button variant="ghost" onClick={() => setSelected(null)}>
              ← All symbols
            </Button>
          </div>

          {chartRows.length > 1 ? (
            <Card pad={space[3]} style={{ marginBottom: space[3] }}>
              <div style={{ color: color.muted, fontSize: 11, marginBottom: 4 }}>
                {selected} price &amp; volume · last {chartRows.length} min
              </div>
              <PriceVolumeChart data={chartRows} height={isMobile ? 160 : 220} />
            </Card>
          ) : (
            <Card pad={space[4]} style={{ marginBottom: space[3] }}>
              <div style={{ color: color.muted, fontSize: 13 }}>
                No recent ticks for {selected} — markets may be closed, or the job hasn’t run a full
                cycle.
              </div>
            </Card>
          )}

          {latest && <Oscillator osc={latest.osc} />}

          {latest && (
            <>
              <div style={{ marginBottom: space[2] }}>
                <InfoTip text={TIP.horizons}>
                  <span
                    style={{
                      color: color.muted,
                      fontSize: 11,
                      borderBottom: `1px dotted ${color.faint}`,
                    }}
                  >
                    What the chips mean
                  </span>
                </InfoTip>{" "}
                <InfoTip text={TIP.bullTrap}>
                  <span
                    style={{
                      color: color.muted,
                      fontSize: 11,
                      borderBottom: `1px dotted ${color.faint}`,
                      marginLeft: 10,
                    }}
                  >
                    Bull/bear traps?
                  </span>
                </InfoTip>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(min(160px, 100%), 1fr))",
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
          )}

          <SectionTitle
            right={(() => {
              const acc = accuracy(detailHistory);
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
            <div style={{ overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: 13,
                  fontFamily: font.mono,
                }}
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
                  {detailHistory.map((row) => (
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
                  {detailHistory.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ padding: 14, color: color.faint }}>
                        No history yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </PageShell>
  );
}

const th: React.CSSProperties = { padding: "10px 14px" };
const td: React.CSSProperties = { padding: "8px 14px" };
