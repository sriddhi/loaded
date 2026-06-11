"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { BarChartView } from "../../components/ui/Chart";
import { color } from "../../theme/tokens";

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

// ── Formatters (money is stored as integer cents) ─────────────────────────────
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

function fmtPct(r: number | null): string {
  return r === null || r === undefined ? "—" : `${(r * 100).toFixed(1)}%`;
}

function fmtNum(r: number | null, suffix = ""): string {
  return r === null || r === undefined ? "—" : `${r.toFixed(2)}${suffix}`;
}

function fmtEps(v: number | null): string {
  return v === null || v === undefined ? "—" : `$${v.toFixed(2)}`;
}

const METRIC_KEYS = [
  "pe",
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
  "roic",
  "net_margin",
  "gross_margin",
  "operating_margin",
  "revenue_growth_yoy",
  "eps_growth_yoy",
  "revenue_cagr_3y",
  "revenue_cagr_5y",
  "eps_cagr_3y",
]);

const METRIC_LABEL: Record<string, string> = {
  pe: "P/E",
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

function fmtMetric(key: string, v: number | null): string {
  if (v === null || v === undefined) return "—";
  return PCT_METRICS.has(key) ? fmtPct(v) : fmtNum(v);
}

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

const card: React.CSSProperties = {
  background: "#111",
  border: "1px solid #222",
  borderRadius: 10,
  padding: 16,
};

export default function FundamentalsPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [tracked, setTracked] = useState<Tracked[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [stmts, setStmts] = useState<StatementsResp | null>(null);
  const [metrics, setMetrics] = useState<MetricsResp | null>(null);
  const [price, setPrice] = useState<PriceResp | null>(null);
  const [period, setPeriod] = useState<"annual" | "quarterly">("annual");
  const [busy, setBusy] = useState(false);
  const [addInput, setAddInput] = useState("");
  const [error, setError] = useState<string | null>(null);

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
        const [sRes, mRes, pRes] = await Promise.all([
          apiFetch(`/fundamentals/${sym}/statements?period=${per}`),
          apiFetch(`/fundamentals/${sym}/metrics?metrics=${METRIC_KEYS.join(",")}&period=${per}`),
          apiFetch(`/fundamentals/${sym}/price`),
        ]);
        setStmts(sRes.ok ? ((await sRes.json()) as StatementsResp) : null);
        setMetrics(mRes.ok ? ((await mRes.json()) as MetricsResp) : null);
        setPrice(pRes.ok ? ((await pRes.json()) as PriceResp) : null);
        if (!sRes.ok) setError(`No statements for ${sym}`);
      } catch {
        setError("Failed to load fundamentals.");
      } finally {
        setBusy(false);
      }
    },
    []
  );

  useEffect(() => {
    void loadTracked();
  }, [loadTracked]);

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
      }}
    >
      <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em", marginBottom: 20 }}>
        Fundamentals
      </h1>

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 24 }}>
        {/* ── Tracklist ── */}
        <aside>
          <form onSubmit={handleAdd} style={{ display: "flex", gap: 6, marginBottom: 12 }}>
            <input
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
              placeholder="Add ticker…"
              style={{
                flex: 1,
                background: "#111",
                border: "1px solid #222",
                borderRadius: 6,
                color: "#f5f5f5",
                padding: "8px 10px",
                fontSize: 13,
                outline: "none",
                textTransform: "uppercase",
              }}
            />
            <button
              type="submit"
              disabled={busy}
              style={{
                background: "#e8ff47",
                color: "#0a0a0a",
                border: "none",
                borderRadius: 6,
                padding: "0 14px",
                fontWeight: 700,
                fontSize: 13,
                cursor: busy ? "default" : "pointer",
              }}
            >
              +
            </button>
          </form>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {tracked.map((t) => {
              const active = t.symbol === selected;
              return (
                <button
                  key={t.symbol}
                  onClick={() => setSelected(t.symbol)}
                  style={{
                    textAlign: "left",
                    background: active ? "#1c1c1c" : "transparent",
                    border: active ? "1px solid #e8ff47" : "1px solid #222",
                    borderRadius: 8,
                    padding: "10px 12px",
                    cursor: "pointer",
                    color: "#f5f5f5",
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{t.symbol}</div>
                  <div
                    style={{
                      color: "#777",
                      fontSize: 11,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {t.name ?? t.sector ?? ""}
                  </div>
                </button>
              );
            })}
            {tracked.length === 0 && (
              <div style={{ color: "#555", fontSize: 13 }}>No tracked tickers yet.</div>
            )}
          </div>
        </aside>

        {/* ── Detail ── */}
        <section>
          {error && <div style={{ color: "#ef4444", fontSize: 13, marginBottom: 12 }}>{error}</div>}
          {!selected && <div style={{ color: "#555" }}>Select a ticker.</div>}

          {selected && (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 16 }}>
                <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{selected}</h2>
                <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 18 }}>
                  {price ? (
                    <span style={{ color: price.stale ? "#f59e0b" : "#22c55e" }}>
                      ${price.price.toFixed(2)}
                      {price.stale ? " (stale)" : ""}
                    </span>
                  ) : (
                    <span style={{ color: "#777" }}>price unavailable</span>
                  )}
                </div>
                {stmts?.as_of && (
                  <div style={{ color: "#555", fontSize: 11, marginLeft: "auto" }}>
                    as of {new Date(stmts.as_of).toLocaleDateString()}
                  </div>
                )}
              </div>

              {/* Metrics cards */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
                  gap: 10,
                  marginBottom: 24,
                }}
              >
                {METRIC_KEYS.map((k) => (
                  <div key={k} style={card}>
                    <div style={{ color: "#777", fontSize: 11 }}>{METRIC_LABEL[k] ?? k}</div>
                    <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                      {fmtMetric(k, metrics?.metrics[k] ?? null)}
                    </div>
                  </div>
                ))}
              </div>

              {/* Period toggle */}
              <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                {(["annual", "quarterly"] as const).map((p) => (
                  <button
                    key={p}
                    onClick={() => setPeriod(p)}
                    style={{
                      background: period === p ? "#e8ff47" : "#111",
                      color: period === p ? "#0a0a0a" : "#f5f5f5",
                      border: "1px solid #222",
                      borderRadius: 6,
                      padding: "6px 14px",
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: "pointer",
                    }}
                  >
                    {p}
                  </button>
                ))}
              </div>

              {/* Revenue + net income trend chart (oldest → newest, in $B) */}
              {(() => {
                const data = [...(stmts?.statements ?? [])].reverse().map((s) => ({
                  x: String(s.fiscal_year ?? s.period_end.slice(0, 4)),
                  Revenue: s.revenue !== null ? s.revenue / 100 / 1e9 : 0,
                  "Net income": s.net_income !== null ? s.net_income / 100 / 1e9 : 0,
                }));
                return data.length > 1 ? (
                  <div style={{ ...card, padding: 14, marginBottom: 12 }}>
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
                  </div>
                ) : null;
              })()}

              {/* Statements table */}
              <div style={{ ...card, overflowX: "auto", padding: 0 }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 13,
                    fontFamily: "var(--font-mono, monospace)",
                  }}
                >
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "12px 16px", color: "#777" }}>
                        Line item
                      </th>
                      {(stmts?.statements ?? []).map((s) => (
                        <th
                          key={s.period_end}
                          style={{ textAlign: "right", padding: "12px 16px", color: "#777" }}
                        >
                          {s.fiscal_year ?? s.period_end}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ROWS.map((row) => (
                      <tr key={row.key} style={{ borderTop: "1px solid #1a1a1a" }}>
                        <td style={{ padding: "10px 16px", color: "#aaa" }}>{row.label}</td>
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
                {busy && <div style={{ padding: 16, color: "#777", fontSize: 13 }}>Loading…</div>}
                {!busy && (stmts?.statements.length ?? 0) === 0 && (
                  <div style={{ padding: 16, color: "#777", fontSize: 13 }}>No statements.</div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
