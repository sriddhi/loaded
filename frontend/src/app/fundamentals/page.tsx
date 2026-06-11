"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { BarChartView, LineChartView } from "../../components/ui/Chart";
import { Button, Card, PageShell, SectionTitle, Stat, useIsMobile } from "../../components/ui";
import { color, font, space } from "../../theme/tokens";

// ── Types ─────────────────────────────────────────────────────────────────────
type Tracked = {
  symbol: string;
  name: string | null;
  sector: string | null;
  market_cap_tier: string | null;
};
type Statement = {
  period_end: string;
  fiscal_year: number | null;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  ebitda: number | null;
  total_assets: number | null;
  total_equity: number | null;
  total_debt: number | null;
  free_cash_flow: number | null;
  eps_diluted: number | null;
};
type StatementsResp = {
  symbol: string;
  period_type: string;
  statements: Statement[];
  as_of: string | null;
};
type MetricsResp = {
  symbol: string;
  metrics: Record<string, number | null>;
  price_used: number | null;
  as_of: string | null;
};
type PriceResp = { symbol: string; price: number; ts: string; stale: boolean };
type ForwardResp = {
  symbol: string;
  price: number | null;
  forward_eps: number | null;
  trailing_eps: number | null;
  forward_pe: number | null;
};

// ── Formatters (money is integer cents) ───────────────────────────────────────
function fmtMoney(cents: number | null): string {
  if (cents === null || cents === undefined) return "—";
  const d = cents / 100;
  const a = Math.abs(d);
  if (a >= 1e12) return `$${(d / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(d / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(d / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${(d / 1e3).toFixed(1)}K`;
  return `$${d.toFixed(0)}`;
}
const fmtPct = (r: number | null): string =>
  r === null || r === undefined ? "—" : `${(r * 100).toFixed(1)}%`;
const fmtNum = (r: number | null): string => (r === null || r === undefined ? "—" : r.toFixed(2));
const fmtEps = (v: number | null): string =>
  v === null || v === undefined ? "—" : `$${v.toFixed(2)}`;

const METRIC_KEYS = [
  "pe",
  "fwd_pe",
  "pb",
  "ps",
  "ev_ebitda",
  "roe",
  "roa",
  "net_margin",
  "gross_margin",
  "operating_margin",
  "debt_to_equity",
  "current_ratio",
  "revenue_growth_yoy",
];
const PCT_METRICS = new Set([
  "roe",
  "roa",
  "net_margin",
  "gross_margin",
  "operating_margin",
  "revenue_growth_yoy",
]);
const METRIC_LABEL: Record<string, string> = {
  pe: "P/E",
  fwd_pe: "Fwd P/E",
  pb: "P/B",
  ps: "P/S",
  ev_ebitda: "EV/EBITDA",
  roe: "ROE",
  roa: "ROA",
  net_margin: "Net margin",
  gross_margin: "Gross margin",
  operating_margin: "Op. margin",
  debt_to_equity: "Debt/Equity",
  current_ratio: "Current ratio",
  revenue_growth_yoy: "Rev growth YoY",
};
const fmtMetric = (key: string, v: number | null): string =>
  v === null || v === undefined ? "—" : PCT_METRICS.has(key) ? fmtPct(v) : fmtNum(v);

const ROWS: { key: keyof Statement; label: string; eps?: boolean }[] = [
  { key: "revenue", label: "Revenue" },
  { key: "gross_profit", label: "Gross profit" },
  { key: "operating_income", label: "Operating income" },
  { key: "net_income", label: "Net income" },
  { key: "ebitda", label: "EBITDA" },
  { key: "total_assets", label: "Total assets" },
  { key: "total_equity", label: "Total equity" },
  { key: "total_debt", label: "Total debt" },
  { key: "free_cash_flow", label: "Free cash flow" },
  { key: "eps_diluted", label: "EPS (diluted)", eps: true },
];

// Chartable series: any statement line or a per-period derived margin.
type Unit = "money" | "pct" | "eps";
type Chartable = { key: string; label: string; unit: Unit; value: (s: Statement) => number | null };
const ratio = (a: number | null, b: number | null): number | null =>
  a !== null && b ? a / b : null;
const CHARTABLE: Chartable[] = [
  { key: "revenue", label: "Revenue", unit: "money", value: (s) => s.revenue },
  { key: "gross_profit", label: "Gross profit", unit: "money", value: (s) => s.gross_profit },
  {
    key: "operating_income",
    label: "Operating income",
    unit: "money",
    value: (s) => s.operating_income,
  },
  { key: "net_income", label: "Net income", unit: "money", value: (s) => s.net_income },
  { key: "ebitda", label: "EBITDA", unit: "money", value: (s) => s.ebitda },
  { key: "free_cash_flow", label: "Free cash flow", unit: "money", value: (s) => s.free_cash_flow },
  { key: "eps_diluted", label: "EPS", unit: "eps", value: (s) => s.eps_diluted },
  {
    key: "gross_margin",
    label: "Gross margin",
    unit: "pct",
    value: (s) => ratio(s.gross_profit, s.revenue),
  },
  {
    key: "operating_margin",
    label: "Op. margin",
    unit: "pct",
    value: (s) => ratio(s.operating_income, s.revenue),
  },
  {
    key: "net_margin",
    label: "Net margin",
    unit: "pct",
    value: (s) => ratio(s.net_income, s.revenue),
  },
];

// ── Deterministic technical summary ───────────────────────────────────────────
type Insight = { text: string; tone: string };
function buildSummary(
  stmts: Statement[],
  periodType: string
): { rows: [string, string, number | null][]; insights: Insight[] } | null {
  if (stmts.length < 2) return null;
  const [cur, prev] = stmts; // newest-first
  const prev2 = stmts[2] ?? null;
  const growth = (a: number | null, b: number | null): number | null =>
    a !== null && b ? (a - b) / Math.abs(b) : null;
  const margin = (s: Statement, k: keyof Statement): number | null =>
    ratio(s[k] as number | null, s.revenue);

  const revG = growth(cur.revenue, prev.revenue);
  const epsG = growth(cur.eps_diluted, prev.eps_diluted);
  const nmCur = margin(cur, "net_income");
  const nmPrev = margin(prev, "net_income");
  const gmCur = margin(cur, "gross_profit");
  const de = cur.total_debt !== null && cur.total_equity ? cur.total_debt / cur.total_equity : null;

  const cmp = periodType === "annual" ? "YoY" : "QoQ";
  const rows: [string, string, number | null][] = [
    ["Revenue", fmtMoney(cur.revenue), revG],
    ["Net income", fmtMoney(cur.net_income), growth(cur.net_income, prev.net_income)],
    ["EPS (diluted)", fmtEps(cur.eps_diluted), epsG],
    ["Net margin", fmtPct(nmCur), nmCur !== null && nmPrev !== null ? nmCur - nmPrev : null],
    [
      "Free cash flow",
      fmtMoney(cur.free_cash_flow),
      growth(cur.free_cash_flow, prev.free_cash_flow),
    ],
    ["Debt / equity", fmtNum(de), null],
  ];

  const insights: Insight[] = [];
  if (revG !== null) {
    const prevG = prev2 ? growth(prev.revenue, prev2.revenue) : null;
    const accel = prevG !== null ? (revG > prevG ? "accelerating" : "decelerating") : null;
    insights.push({
      text: `Revenue ${revG >= 0 ? "grew" : "fell"} ${(Math.abs(revG) * 100).toFixed(1)}% ${cmp}${accel ? ` and is ${accel}` : ""}.`,
      tone: revG >= 0 ? color.up : color.down,
    });
  }
  if (nmCur !== null && nmPrev !== null) {
    const bps = Math.round((nmCur - nmPrev) * 10000);
    insights.push({
      text: `Net margin ${bps >= 0 ? "expanded" : "contracted"} ${Math.abs(bps)} bps to ${(nmCur * 100).toFixed(1)}%.`,
      tone: bps >= 0 ? color.up : color.down,
    });
  }
  if (
    prev.net_income !== null &&
    cur.net_income !== null &&
    prev.net_income < 0 &&
    cur.net_income >= 0
  ) {
    insights.push({
      text: "Turned profitable this period (net income crossed zero).",
      tone: color.up,
    });
  }
  if (epsG !== null) {
    insights.push({
      text: `Diluted EPS ${epsG >= 0 ? "up" : "down"} ${(Math.abs(epsG) * 100).toFixed(1)}% ${cmp}.`,
      tone: epsG >= 0 ? color.up : color.down,
    });
  }
  if (gmCur !== null)
    insights.push({
      text: `Gross margin ${(gmCur * 100).toFixed(1)}% — ${gmCur > 0.5 ? "asset-light economics" : "capital-intensive economics"}.`,
      tone: color.muted,
    });
  if (de !== null)
    insights.push({
      text: `Leverage ${de.toFixed(2)}× debt/equity — ${de < 1 ? "conservatively financed" : "elevated leverage"}.`,
      tone: de < 1 ? color.muted : color.warn,
    });

  return { rows, insights };
}

export default function FundamentalsPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const isMobile = useIsMobile();

  const [tracked, setTracked] = useState<Tracked[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [stmts, setStmts] = useState<StatementsResp | null>(null);
  const [metrics, setMetrics] = useState<MetricsResp | null>(null);
  const [price, setPrice] = useState<PriceResp | null>(null);
  const [forward, setForward] = useState<ForwardResp | null>(null);
  const [period, setPeriod] = useState<"annual" | "quarterly">("annual");
  const [busy, setBusy] = useState(false);
  const [addInput, setAddInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [chartKeys, setChartKeys] = useState<string[]>(["revenue", "net_income"]);
  const [chartMode, setChartMode] = useState<"value" | "indexed">("value");

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const loadTracked = useCallback(async (): Promise<void> => {
    const res = await apiFetch("/fundamentals/tracked");
    if (!res.ok) return;
    const list = (await res.json()) as Tracked[];
    setTracked(list);
    setSelected((cur) => cur ?? list[0]?.symbol ?? null);
  }, []);

  const loadDetail = useCallback(
    async (sym: string, per: "annual" | "quarterly"): Promise<void> => {
      setBusy(true);
      setError(null);
      try {
        const [sRes, mRes, pRes, fRes] = await Promise.all([
          apiFetch(`/fundamentals/${sym}/statements?period=${per}`),
          apiFetch(
            `/fundamentals/${sym}/metrics?metrics=${METRIC_KEYS.filter((k) => k !== "fwd_pe").join(",")}&period=${per}`
          ),
          apiFetch(`/fundamentals/${sym}/price`),
          apiFetch(`/fundamentals/${sym}/forward`),
        ]);
        setStmts(sRes.ok ? ((await sRes.json()) as StatementsResp) : null);
        setMetrics(mRes.ok ? ((await mRes.json()) as MetricsResp) : null);
        setPrice(pRes.ok ? ((await pRes.json()) as PriceResp) : null);
        setForward(fRes.ok ? ((await fRes.json()) as ForwardResp) : null);
        if (!sRes.ok) setError(`No statements for ${sym}`);
      } catch {
        setError("Failed to load fundamentals.");
      } finally {
        setBusy(false);
      }
    },
    []
  );

  useEffect(() => void loadTracked(), [loadTracked]);
  useEffect(() => {
    if (selected) void loadDetail(selected, period);
  }, [selected, period, loadDetail]);

  async function handleAdd(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    const sym = addInput.trim().toUpperCase();
    if (!sym) return;
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch(`/fundamentals/tracked/${sym}`, { method: "POST" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `Could not add ${sym}`);
      }
      setAddInput("");
      await loadTracked();
      setSelected(sym);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Add failed.");
    } finally {
      setBusy(false);
    }
  }

  // Comparative chart data (oldest → newest).
  const chartData = useMemo(() => {
    const series = [...(stmts?.statements ?? [])].reverse();
    const chosen = CHARTABLE.filter((c) => chartKeys.includes(c.key));
    const firsts: Record<string, number | null> = {};
    for (const c of chosen)
      firsts[c.key] = series.map((s) => c.value(s)).find((v) => v !== null && v !== 0) ?? null;
    return series.map((s) => {
      const row: Record<string, number | string> = {
        x: String(s.fiscal_year ?? s.period_end.slice(0, 4)),
      };
      for (const c of chosen) {
        const raw = c.value(s);
        if (raw === null) continue;
        if (chartMode === "indexed") {
          const base = firsts[c.key];
          if (base) row[c.label] = (raw / base) * 100;
        } else {
          row[c.label] = c.unit === "money" ? raw / 100 / 1e9 : c.unit === "pct" ? raw * 100 : raw;
        }
      }
      return row;
    });
  }, [stmts, chartKeys, chartMode]);

  const chosenChartables = CHARTABLE.filter((c) => chartKeys.includes(c.key));
  const mixedUnits = new Set(chosenChartables.map((c) => c.unit)).size > 1;
  const summary = useMemo(
    () => (stmts ? buildSummary(stmts.statements, stmts.period_type) : null),
    [stmts]
  );

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  return (
    <PageShell title="Fundamentals">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "240px 1fr",
          gap: space[5],
        }}
      >
        {/* ── Tracklist ── */}
        <aside>
          <form onSubmit={handleAdd} style={{ display: "flex", gap: 6, marginBottom: space[3] }}>
            <input
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
              placeholder="Add ticker…"
              style={{
                flex: 1,
                background: color.surface,
                border: `1px solid ${color.border}`,
                borderRadius: 6,
                color: color.fg,
                padding: "8px 10px",
                fontSize: 13,
                outline: "none",
                textTransform: "uppercase",
              }}
            />
            <Button variant="primary" disabled={busy}>
              +
            </Button>
          </form>
          <div
            style={{
              display: isMobile ? "flex" : "flex",
              flexDirection: isMobile ? "row" : "column",
              gap: 6,
              overflowX: isMobile ? "auto" : "visible",
            }}
          >
            {tracked.map((t) => (
              <button
                key={t.symbol}
                onClick={() => setSelected(t.symbol)}
                style={{
                  textAlign: "left",
                  background: t.symbol === selected ? color.surface2 : "transparent",
                  border: `1px solid ${t.symbol === selected ? color.borderStrong : color.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                  cursor: "pointer",
                  color: color.fg,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 14 }}>{t.symbol}</div>
                {!isMobile && (
                  <div
                    style={{
                      color: color.muted,
                      fontSize: 11,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      maxWidth: 200,
                    }}
                  >
                    {t.name ?? t.sector ?? ""}
                  </div>
                )}
              </button>
            ))}
            {tracked.length === 0 && (
              <div style={{ color: color.faint, fontSize: 13 }}>No tracked tickers yet.</div>
            )}
          </div>
        </aside>

        {/* ── Detail ── */}
        <section style={{ minWidth: 0 }}>
          {error && (
            <div style={{ color: color.down, fontSize: 13, marginBottom: 12 }}>{error}</div>
          )}
          {!selected && <div style={{ color: color.faint }}>Select a ticker.</div>}

          {selected && (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 14,
                  marginBottom: space[4],
                  flexWrap: "wrap",
                }}
              >
                <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{selected}</h2>
                <span style={{ fontFamily: font.mono, fontSize: 18 }}>
                  {price ? (
                    <span style={{ color: price.stale ? color.warn : color.up }}>
                      ${price.price.toFixed(2)}
                      {price.stale ? " (stale)" : ""}
                    </span>
                  ) : (
                    <span style={{ color: color.muted }}>price unavailable</span>
                  )}
                </span>
                {stmts?.as_of && (
                  <span style={{ color: color.faint, fontSize: 11, marginLeft: "auto" }}>
                    as of {new Date(stmts.as_of).toLocaleDateString()}
                  </span>
                )}
              </div>

              {/* Metrics cards (Fwd P/E filled from the forward endpoint) */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))",
                  gap: space[2],
                  marginBottom: space[5],
                }}
              >
                {METRIC_KEYS.map((k) => {
                  const v =
                    k === "fwd_pe" ? (forward?.forward_pe ?? null) : (metrics?.metrics[k] ?? null);
                  return (
                    <Card key={k} pad={space[3]}>
                      <div style={{ color: color.muted, fontSize: 11 }}>{METRIC_LABEL[k] ?? k}</div>
                      <div
                        style={{
                          fontSize: 18,
                          fontWeight: 700,
                          marginTop: 4,
                          color: k === "fwd_pe" ? color.hue : color.fg,
                        }}
                      >
                        {k === "fwd_pe" ? fmtNum(v) : fmtMetric(k, v)}
                      </div>
                    </Card>
                  );
                })}
              </div>

              {/* Technical summary + insights */}
              {summary && (
                <Card pad={space[4]} style={{ marginBottom: space[5] }}>
                  <SectionTitle>
                    Technical summary —{" "}
                    {stmts?.statements[0]?.fiscal_year ?? stmts?.statements[0]?.period_end} vs prior
                  </SectionTitle>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))",
                      gap: space[3],
                      marginBottom: space[3],
                    }}
                  >
                    {summary.rows.map(([label, val, chg]) => (
                      <Stat
                        key={label}
                        label={label}
                        value={val}
                        sub={
                          chg === null ? undefined : (
                            <span style={{ color: chg >= 0 ? color.up : color.down }}>
                              {chg >= 0 ? "▲" : "▼"} {Math.abs(chg * 100).toFixed(1)}%
                            </span>
                          )
                        }
                      />
                    ))}
                  </div>
                  <ul
                    style={{
                      margin: 0,
                      paddingLeft: 18,
                      display: "flex",
                      flexDirection: "column",
                      gap: 5,
                    }}
                  >
                    {summary.insights.map((ins, i) => (
                      <li key={i} style={{ fontSize: 13, color: ins.tone, lineHeight: 1.5 }}>
                        <span style={{ color: color.fg }}>{ins.text}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {/* Period toggle */}
              <div style={{ display: "flex", gap: space[2], marginBottom: space[3] }}>
                {(["annual", "quarterly"] as const).map((p) => (
                  <Button
                    key={p}
                    variant="ghost"
                    active={period === p}
                    onClick={() => setPeriod(p)}
                  >
                    {p}
                  </Button>
                ))}
              </div>

              {/* Comparative metric chart — pick ANY metrics */}
              <Card pad={space[4]} style={{ marginBottom: space[4] }}>
                <SectionTitle
                  right={
                    <Button
                      variant="ghost"
                      active={chartMode === "indexed"}
                      onClick={() => setChartMode((m) => (m === "indexed" ? "value" : "indexed"))}
                    >
                      {chartMode === "indexed" ? "Indexed = 100" : "Absolute"}
                    </Button>
                  }
                >
                  Compare metrics
                </SectionTitle>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: space[3] }}>
                  {CHARTABLE.map((c) => {
                    const on = chartKeys.includes(c.key);
                    return (
                      <button
                        key={c.key}
                        onClick={() =>
                          setChartKeys((cur) =>
                            cur.includes(c.key) ? cur.filter((k) => k !== c.key) : [...cur, c.key]
                          )
                        }
                        style={{
                          cursor: "pointer",
                          background: on ? color.surface2 : "transparent",
                          color: on ? color.fg : color.muted,
                          border: `1px solid ${on ? color.borderStrong : color.border}`,
                          borderRadius: 6,
                          padding: "3px 10px",
                          fontSize: 12,
                        }}
                      >
                        {c.label}
                      </button>
                    );
                  })}
                </div>
                {mixedUnits && chartMode === "value" && (
                  <div style={{ color: color.warn, fontSize: 11, marginBottom: 6 }}>
                    Mixed units ($/%/EPS) on one axis — switch to “Indexed = 100” for a fair
                    comparison.
                  </div>
                )}
                {chartData.length > 1 && chosenChartables.length > 0 ? (
                  <LineChartView
                    data={chartData}
                    xKey="x"
                    height={240}
                    showAxes
                    series={chosenChartables.map((c) => ({ key: c.label, label: c.label }))}
                  />
                ) : (
                  <div style={{ color: color.faint, fontSize: 13 }}>
                    Pick one or more metrics to chart.
                  </div>
                )}
                <div style={{ color: color.faint, fontSize: 10, marginTop: 6 }}>
                  {chartMode === "value"
                    ? "Money in $B · margins in % · EPS in $"
                    : "Indexed to 100 at the first period"}
                </div>
              </Card>

              {/* Revenue + net income bars */}
              {(() => {
                const data = [...(stmts?.statements ?? [])].reverse().map((s) => ({
                  x: String(s.fiscal_year ?? s.period_end.slice(0, 4)),
                  Revenue: s.revenue !== null ? s.revenue / 100 / 1e9 : 0,
                  "Net income": s.net_income !== null ? s.net_income / 100 / 1e9 : 0,
                }));
                return data.length > 1 ? (
                  <Card pad={space[4]} style={{ marginBottom: space[4] }}>
                    <div style={{ color: color.muted, fontSize: 11, marginBottom: 6 }}>
                      Revenue &amp; net income ($B)
                    </div>
                    <BarChartView
                      data={data}
                      xKey="x"
                      height={200}
                      series={[
                        { key: "Revenue", color: color.hue },
                        { key: "Net income", color: color.fg },
                      ]}
                    />
                  </Card>
                ) : null;
              })()}

              {/* Statements table */}
              <Card pad={0} style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 13,
                    fontFamily: font.mono,
                  }}
                >
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "12px 16px", color: color.muted }}>
                        Line item
                      </th>
                      {(stmts?.statements ?? []).map((s) => (
                        <th
                          key={s.period_end}
                          style={{ textAlign: "right", padding: "12px 16px", color: color.muted }}
                        >
                          {s.fiscal_year ?? s.period_end}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ROWS.map((row) => (
                      <tr key={row.key} style={{ borderTop: `1px solid ${color.border}` }}>
                        <td style={{ padding: "10px 16px", color: color.muted }}>{row.label}</td>
                        {(stmts?.statements ?? []).map((s) => (
                          <td
                            key={s.period_end}
                            style={{ padding: "10px 16px", textAlign: "right" }}
                          >
                            {row.eps
                              ? fmtEps(s[row.key] as number | null)
                              : fmtMoney(s[row.key] as number | null)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {busy && (
                  <div style={{ padding: 16, color: color.muted, fontSize: 13 }}>Loading…</div>
                )}
                {!busy && (stmts?.statements.length ?? 0) === 0 && (
                  <div style={{ padding: 16, color: color.muted, fontSize: 13 }}>
                    No statements.
                  </div>
                )}
              </Card>
              <div style={{ height: space[6] }} />
            </>
          )}
        </section>
      </div>
    </PageShell>
  );
}
