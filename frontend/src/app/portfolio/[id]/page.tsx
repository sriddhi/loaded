"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "../../../context/AuthContext";
import { apiFetch } from "../../../lib/api";
import { Badge, Button, Card, PageShell, SectionTitle, Stat, Tabs } from "../../../components/ui";
import { BarChartView, LineChartView } from "../../../components/ui/Chart";
import { color, font, space } from "../../../theme/tokens";

type Holding = {
  symbol: string;
  name: string | null;
  sector: string | null;
  qty: number;
  avg_cost: number;
  cost_basis: number;
  price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pct: number | null;
  weight_pct: number | null;
  realized_pnl: number;
  score?: Score | null;
};

type Detail = {
  id: number;
  name: string;
  kind: string;
  cash: number;
  equity_value: number | null;
  total_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  holdings: Holding[];
};

type Tx = {
  id: number;
  symbol: string | null;
  tx_type: string;
  qty: number | null;
  price: number | null;
  amount: number;
  fees: number;
  trade_date: string;
  note: string | null;
  source: string;
};

type Score = { composite: number | null; candidate: string; rank: number | null };

type Perf = {
  series: { date: string; total_value: number; twr_index: number }[];
  twr_pct: number | null;
  simple_return_pct: number | null;
  beta: number | null;
};

type Check = {
  id: string;
  status: "ok" | "warn" | "flag" | "info";
  headline: string;
  detail: string;
  metric: number | null;
};
type Insights = {
  holdings_signals: {
    summary: string;
    items: {
      symbol: string;
      weight_pct: number;
      candidate: string;
      composite: number | null;
      reasons: string[];
    }[];
  };
  macro_impacts: {
    alert_id: string;
    meaning: string;
    impact: string;
    fired_since: string | null;
    affected: { sector: string; portfolio_weight_pct: number; direction: string }[];
  }[];
  upcoming_earnings: {
    symbol: string;
    earnings_date: string;
    hour: string | null;
    weight_pct: number;
  }[];
  health: { diversification_score: number; checks: Check[] };
};
type Suggestion = {
  symbol: string;
  action: string;
  suggested_qty: number;
  est_cost: number;
  target_weight_pct: number;
  reason: string;
};
type Commentary = { markdown: string; generated_at: string; cached: boolean; version: number };

type Allocation = {
  by_sector: { sector: string; weight_pct: number; value: number }[];
  concentration: { top1_pct: number; top5_pct: number; hhi: number; label: string };
  cash_pct: number;
};

const usd = (v: number | null | undefined): string =>
  v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD" });

const TX_TYPES = ["buy", "sell", "dividend", "deposit", "withdrawal"] as const;

export default function PortfolioDetailPage(): React.JSX.Element {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const pid = params.id;
  const { user, loading: authLoading } = useAuth();
  const [tab, setTab] = useState("Overview");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [txs, setTxs] = useState<Tx[] | null>(null);
  const [alloc, setAlloc] = useState<Allocation | null>(null);
  const [perf, setPerf] = useState<Perf | null>(null);
  const [scores, setScores] = useState<Record<string, Score | null>>({});
  const [insightsData, setInsightsData] = useState<Insights | null>(null);
  const [sugs, setSugs] = useState<Suggestion[] | null>(null);
  const [sugMode, setSugMode] = useState<"score_weighted" | "equal_weight">("score_weighted");
  const [commentary, setCommentary] = useState<Commentary | null>(null);
  const [commentaryBusy, setCommentaryBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // tx form state
  const [txType, setTxType] = useState<(typeof TX_TYPES)[number]>("buy");
  const [fSymbol, setFSymbol] = useState("");
  const [fQty, setFQty] = useState("");
  const [fPrice, setFPrice] = useState("");
  const [fAmount, setFAmount] = useState("");
  const [fFees, setFFees] = useState("");
  const [fDate, setFDate] = useState(new Date().toISOString().slice(0, 10));

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async (): Promise<void> => {
    try {
      const [dRes, tRes, aRes, pRes, hRes] = await Promise.all([
        apiFetch(`/portfolio/${pid}`),
        apiFetch(`/portfolio/${pid}/transactions?limit=100`),
        apiFetch(`/portfolio/${pid}/allocation`),
        apiFetch(`/portfolio/${pid}/performance?range=3m`),
        apiFetch(`/portfolio/${pid}/holdings`),
      ]);
      if (!dRes.ok) {
        setError(dRes.status === 404 ? "Portfolio not found." : `Load failed (${dRes.status}).`);
        return;
      }
      setDetail((await dRes.json()) as Detail);
      setTxs(tRes.ok ? ((await tRes.json()) as { items: Tx[] }).items : []);
      setAlloc(aRes.ok ? ((await aRes.json()) as Allocation) : null);
      setPerf(pRes.ok ? ((await pRes.json()) as Perf) : null);
      if (hRes.ok) {
        const hb = (await hRes.json()) as { holdings: (Holding & { score?: Score | null })[] };
        const m: Record<string, Score | null> = {};
        for (const h of hb.holdings) m[h.symbol] = h.score ?? null;
        setScores(m);
      }
      setError(null);
      const [iRes, cRes] = await Promise.all([
        apiFetch(`/portfolio/${pid}/insights`),
        apiFetch(`/portfolio/${pid}/commentary`),
      ]);
      setInsightsData(iRes.ok ? ((await iRes.json()) as Insights) : null);
      setCommentary(cRes.ok ? ((await cRes.json()) as Commentary) : null);
    } catch {
      setError("Failed to load portfolio.");
    }
  }, [pid]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addTx(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const isShare = txType === "buy" || txType === "sell";
    const body: Record<string, unknown> = { tx_type: txType, trade_date: fDate };
    if (isShare) {
      body.symbol = fSymbol.trim().toUpperCase();
      body.qty = parseFloat(fQty);
      body.price = parseFloat(fPrice);
      if (fFees) body.fees = parseFloat(fFees);
    } else {
      body.amount = parseFloat(fAmount);
      if (txType === "dividend" && fSymbol.trim()) body.symbol = fSymbol.trim().toUpperCase();
    }
    try {
      const res = await apiFetch(`/portfolio/${pid}/transactions`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const eb = (await res.json().catch(() => ({}))) as { detail?: unknown };
        throw new Error(
          typeof eb.detail === "string" ? eb.detail : "Transaction rejected — check the fields"
        );
      }
      setFSymbol("");
      setFQty("");
      setFPrice("");
      setFAmount("");
      setFFees("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Transaction failed.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteTx(id: number): Promise<void> {
    if (!confirm("Delete this transaction? Holdings will be rebuilt.")) return;
    const res = await apiFetch(`/portfolio/${pid}/transactions/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const eb = (await res.json().catch(() => ({}))) as { detail?: string };
      setError(eb.detail ?? "Delete failed");
    }
    await load();
  }

  async function loadSuggestions(mode: "score_weighted" | "equal_weight"): Promise<void> {
    setSugMode(mode);
    const res = await apiFetch(`/portfolio/${pid}/suggestions`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    if (res.ok) {
      const body = (await res.json()) as { suggestions: Suggestion[] };
      setSugs(body.suggestions);
    }
  }

  async function generateCommentary(force: boolean): Promise<void> {
    setCommentaryBusy(true);
    try {
      const res = await apiFetch(`/portfolio/${pid}/commentary`, {
        method: "POST",
        body: JSON.stringify({ force }),
      });
      if (res.ok) setCommentary((await res.json()) as Commentary);
      else {
        const eb = (await res.json().catch(() => ({}))) as { detail?: string };
        setError(eb.detail ?? "Commentary unavailable");
      }
    } finally {
      setCommentaryBusy(false);
    }
  }

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  const isSynced = detail?.kind === "alpaca_paper";
  const inputStyle: React.CSSProperties = {
    background: color.surface2,
    border: `1px solid ${color.border}`,
    borderRadius: 6,
    color: color.fg,
    padding: "7px 10px",
    fontSize: 13,
    fontFamily: font.mono,
    flex: "1 1 110px",
    minWidth: 90,
    maxWidth: 180,
  };

  return (
    <PageShell
      title={detail?.name ?? "Portfolio"}
      maxWidth={1100}
      right={
        <Button variant="ghost" onClick={() => router.push("/portfolio")}>
          ← All portfolios
        </Button>
      }
      subtitle="Heuristic, educational — not financial advice."
    >
      {error && <div style={{ color: color.down, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      <div style={{ marginBottom: space[4] }}>
        <Tabs
          options={["Overview", "Holdings", "Transactions", "Insights"]}
          value={tab}
          onChange={setTab}
        />
      </div>

      {tab === "Overview" && detail && (
        <>
          <Card pad={space[4]} style={{ marginBottom: space[4] }}>
            <div style={{ display: "flex", gap: space[6], flexWrap: "wrap" }}>
              <Stat label="Total value" value={usd(detail.total_value)} />
              <Stat label="Equity" value={usd(detail.equity_value)} />
              <Stat label="Cash" value={usd(detail.cash)} />
              <Stat
                label="Unrealized P&L"
                value={usd(detail.unrealized_pnl)}
                tone={(detail.unrealized_pnl ?? 0) >= 0 ? color.up : color.down}
              />
              <Stat
                label="Realized P&L"
                value={usd(detail.realized_pnl)}
                tone={(detail.realized_pnl ?? 0) >= 0 ? color.up : color.down}
              />
            </div>
          </Card>
          {perf && perf.series.length > 1 && (
            <Card pad={space[4]} style={{ marginBottom: space[4] }}>
              <SectionTitle
                right={
                  <span style={{ display: "flex", gap: 6 }}>
                    {perf.twr_pct != null && (
                      <Badge tone={perf.twr_pct >= 0 ? color.up : color.down}>
                        TWR {perf.twr_pct}%
                      </Badge>
                    )}
                    {perf.beta != null && <Badge>beta {perf.beta}</Badge>}
                  </span>
                }
              >
                Performance (3m)
              </SectionTitle>
              <LineChartView
                height={180}
                showAxes
                data={perf.series.map((s2) => ({ x: s2.date.slice(5), value: s2.total_value }))}
                series={[{ key: "value", label: "Total value" }]}
              />
            </Card>
          )}
          {alloc && alloc.by_sector.length > 0 && (
            <Card pad={space[4]}>
              <SectionTitle
                right={
                  <span style={{ display: "flex", gap: 6 }}>
                    <Badge>{alloc.concentration.label}</Badge>
                    <Badge>top1 {alloc.concentration.top1_pct}%</Badge>
                    <Badge>cash {alloc.cash_pct}%</Badge>
                  </span>
                }
              >
                Sector allocation
              </SectionTitle>
              <BarChartView
                height={220}
                data={alloc.by_sector.map((s) => ({ x: s.sector, weight: s.weight_pct }))}
                series={[{ key: "weight", label: "% of equity" }]}
              />
            </Card>
          )}
        </>
      )}

      {tab === "Holdings" &&
        (detail && detail.holdings.length > 0 ? (
          <Card pad={space[4]}>
            <div style={{ overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: 12,
                  fontFamily: font.mono,
                }}
              >
                <thead>
                  <tr style={{ color: color.muted, textAlign: "right" }}>
                    <th style={{ textAlign: "left", padding: 6 }}>Symbol</th>
                    <th style={{ padding: 6 }}>Qty</th>
                    <th style={{ padding: 6 }}>Avg cost</th>
                    <th style={{ padding: 6 }}>Price</th>
                    <th style={{ padding: 6 }}>Value</th>
                    <th style={{ padding: 6 }}>Unreal $</th>
                    <th style={{ padding: 6 }}>Unreal %</th>
                    <th style={{ padding: 6 }}>Weight</th>
                    <th style={{ padding: 6 }}>Realized</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.holdings.map((h) => (
                    <tr key={h.symbol} style={{ borderTop: `1px solid ${color.border}` }}>
                      <td style={{ padding: 6 }}>
                        <span style={{ fontWeight: 700 }}>{h.symbol}</span>
                        <span style={{ color: color.faint, marginLeft: 8, fontSize: 10 }}>
                          {h.sector ?? ""}
                        </span>
                        {scores[h.symbol] && (
                          <span style={{ marginLeft: 8 }}>
                            <Badge
                              tone={
                                scores[h.symbol]!.candidate.includes("buy")
                                  ? color.up
                                  : scores[h.symbol]!.candidate.includes("sell")
                                    ? color.down
                                    : color.muted
                              }
                            >
                              {scores[h.symbol]!.candidate.replace("_", " ")}
                            </Badge>
                          </span>
                        )}
                      </td>
                      <td style={{ padding: 6, textAlign: "right" }}>{h.qty}</td>
                      <td style={{ padding: 6, textAlign: "right" }}>{usd(h.avg_cost)}</td>
                      <td style={{ padding: 6, textAlign: "right" }}>{usd(h.price)}</td>
                      <td style={{ padding: 6, textAlign: "right" }}>{usd(h.market_value)}</td>
                      <td
                        style={{
                          padding: 6,
                          textAlign: "right",
                          color: (h.unrealized_pnl ?? 0) >= 0 ? color.up : color.down,
                        }}
                      >
                        {usd(h.unrealized_pnl)}
                      </td>
                      <td
                        style={{
                          padding: 6,
                          textAlign: "right",
                          color: (h.unrealized_pct ?? 0) >= 0 ? color.up : color.down,
                        }}
                      >
                        {h.unrealized_pct == null ? "—" : `${h.unrealized_pct}%`}
                      </td>
                      <td style={{ padding: 6, textAlign: "right" }}>
                        {h.weight_pct == null ? "—" : `${h.weight_pct}%`}
                      </td>
                      <td
                        style={{
                          padding: 6,
                          textAlign: "right",
                          color: h.realized_pnl >= 0 ? color.up : color.down,
                        }}
                      >
                        {usd(h.realized_pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ) : (
          <div style={{ color: color.muted, fontSize: 13 }}>
            No holdings yet — add a buy under Transactions{isSynced ? " (or re-sync)" : ""}.
          </div>
        ))}

      {tab === "Transactions" && (
        <>
          {isSynced ? (
            <Card pad={space[4]} style={{ marginBottom: space[4] }}>
              <div style={{ color: color.muted, fontSize: 13 }}>
                This portfolio is synced from Alpaca Paper and is read-only — holdings update on
                each sync.
              </div>
            </Card>
          ) : (
            <Card pad={space[4]} style={{ marginBottom: space[4] }}>
              <SectionTitle>Add transaction</SectionTitle>
              <form
                onSubmit={(e) => void addTx(e)}
                style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}
              >
                <select
                  value={txType}
                  onChange={(e) => setTxType(e.target.value as (typeof TX_TYPES)[number])}
                  style={{ ...inputStyle, width: 130 }}
                >
                  {TX_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                {(txType === "buy" || txType === "sell" || txType === "dividend") && (
                  <input
                    value={fSymbol}
                    onChange={(e) => setFSymbol(e.target.value)}
                    placeholder="symbol"
                    style={inputStyle}
                  />
                )}
                {(txType === "buy" || txType === "sell") && (
                  <>
                    <input
                      value={fQty}
                      onChange={(e) => setFQty(e.target.value)}
                      placeholder="qty"
                      style={inputStyle}
                    />
                    <input
                      value={fPrice}
                      onChange={(e) => setFPrice(e.target.value)}
                      placeholder="price $"
                      style={inputStyle}
                    />
                    <input
                      value={fFees}
                      onChange={(e) => setFFees(e.target.value)}
                      placeholder="fees $"
                      style={inputStyle}
                    />
                  </>
                )}
                {txType !== "buy" && txType !== "sell" && (
                  <input
                    value={fAmount}
                    onChange={(e) => setFAmount(e.target.value)}
                    placeholder="amount $"
                    style={inputStyle}
                  />
                )}
                <input
                  type="date"
                  value={fDate}
                  onChange={(e) => setFDate(e.target.value)}
                  style={{ ...inputStyle, width: 150 }}
                />
                <Button variant="primary" disabled={busy}>
                  Add
                </Button>
              </form>
            </Card>
          )}

          {txs && txs.length > 0 ? (
            <Card pad={space[4]}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: 12,
                  fontFamily: font.mono,
                }}
              >
                <thead>
                  <tr style={{ color: color.muted, textAlign: "right" }}>
                    <th style={{ textAlign: "left", padding: 6 }}>Date</th>
                    <th style={{ textAlign: "left", padding: 6 }}>Type</th>
                    <th style={{ textAlign: "left", padding: 6 }}>Symbol</th>
                    <th style={{ padding: 6 }}>Qty</th>
                    <th style={{ padding: 6 }}>Price</th>
                    <th style={{ padding: 6 }}>Cash effect</th>
                    <th style={{ padding: 6 }} />
                  </tr>
                </thead>
                <tbody>
                  {txs.map((t) => (
                    <tr key={t.id} style={{ borderTop: `1px solid ${color.border}` }}>
                      <td style={{ padding: 6 }}>{t.trade_date}</td>
                      <td style={{ padding: 6 }}>
                        <Badge
                          tone={
                            t.tx_type === "buy"
                              ? color.hue
                              : t.tx_type === "sell"
                                ? color.warn
                                : color.muted
                          }
                        >
                          {t.tx_type}
                        </Badge>
                      </td>
                      <td style={{ padding: 6 }}>{t.symbol ?? "—"}</td>
                      <td style={{ padding: 6, textAlign: "right" }}>{t.qty ?? "—"}</td>
                      <td style={{ padding: 6, textAlign: "right" }}>{usd(t.price)}</td>
                      <td
                        style={{
                          padding: 6,
                          textAlign: "right",
                          color: t.amount >= 0 ? color.up : color.down,
                        }}
                      >
                        {usd(t.amount)}
                      </td>
                      <td style={{ padding: 6, textAlign: "right" }}>
                        {!isSynced && (
                          <Button variant="danger" onClick={() => void deleteTx(t.id)}>
                            ✕
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : (
            <div style={{ color: color.muted, fontSize: 13 }}>No transactions yet.</div>
          )}
        </>
      )}
      {tab === "Insights" && (
        <>
          <Card pad={space[4]} style={{ marginBottom: space[4] }}>
            <SectionTitle
              right={
                <Badge tone={color.hue} filled>
                  {insightsData?.health.diversification_score ?? "—"}/100 diversified
                </Badge>
              }
            >
              Portfolio health
            </SectionTitle>
            {(insightsData?.health.checks ?? []).map((c) => (
              <div
                key={c.id}
                style={{ display: "flex", gap: 10, alignItems: "baseline", marginTop: 6 }}
              >
                <Badge
                  tone={
                    c.status === "flag"
                      ? color.down
                      : c.status === "warn"
                        ? color.warn
                        : color.muted
                  }
                  filled={c.status === "flag"}
                >
                  {c.status}
                </Badge>
                <span style={{ fontSize: 12, fontWeight: 600 }}>{c.headline}</span>
                <span style={{ fontSize: 12, color: color.muted }}>{c.detail}</span>
              </div>
            ))}
          </Card>

          <Card pad={space[4]} style={{ marginBottom: space[4] }}>
            <SectionTitle>Holdings vs screener</SectionTitle>
            <div style={{ fontSize: 12, color: color.muted, marginBottom: 8 }}>
              {insightsData?.holdings_signals.summary ?? "…"}
            </div>
            {(insightsData?.holdings_signals.items ?? []).map((it) => (
              <div key={it.symbol} style={{ fontSize: 12, marginTop: 4, fontFamily: font.mono }}>
                <span style={{ fontWeight: 700 }}>{it.symbol}</span>{" "}
                <Badge
                  tone={
                    it.candidate.includes("buy")
                      ? color.up
                      : it.candidate.includes("sell")
                        ? color.down
                        : color.muted
                  }
                >
                  {it.candidate.replace("_", " ")}
                </Badge>{" "}
                <span style={{ color: color.faint }}>
                  comp {it.composite ?? "—"} · {it.weight_pct}% of equity
                </span>
              </div>
            ))}
          </Card>

          {(insightsData?.macro_impacts.length ?? 0) > 0 && (
            <Card pad={space[4]} style={{ marginBottom: space[4] }}>
              <SectionTitle>Macro alerts touching your sectors</SectionTitle>
              {insightsData!.macro_impacts.map((m) => (
                <div key={m.alert_id} style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>
                    {m.alert_id}{" "}
                    {m.affected.map((a) => (
                      <Badge
                        key={a.sector}
                        tone={a.direction === "tailwind" ? color.up : color.warn}
                      >
                        {a.sector} {a.portfolio_weight_pct}% {a.direction}
                      </Badge>
                    ))}
                  </div>
                  <div style={{ fontSize: 12, color: color.muted, marginTop: 2 }}>{m.meaning}</div>
                </div>
              ))}
            </Card>
          )}

          {(insightsData?.upcoming_earnings.length ?? 0) > 0 && (
            <Card pad={space[4]} style={{ marginBottom: space[4] }}>
              <SectionTitle>Earnings in the next 14 days</SectionTitle>
              {insightsData!.upcoming_earnings.map((e) => (
                <div
                  key={`${e.symbol}-${e.earnings_date}`}
                  style={{ fontSize: 12, fontFamily: font.mono, marginTop: 4 }}
                >
                  {e.earnings_date} · <b>{e.symbol}</b> ({e.weight_pct}% of equity)
                  {e.hour ? ` · ${e.hour}` : ""}
                </div>
              ))}
            </Card>
          )}

          <Card pad={space[4]} style={{ marginBottom: space[4] }}>
            <SectionTitle
              right={
                <span style={{ display: "flex", gap: 6 }}>
                  <Button
                    variant="ghost"
                    active={sugMode === "score_weighted"}
                    onClick={() => void loadSuggestions("score_weighted")}
                  >
                    score weighted
                  </Button>
                  <Button
                    variant="ghost"
                    active={sugMode === "equal_weight"}
                    onClick={() => void loadSuggestions("equal_weight")}
                  >
                    equal weight
                  </Button>
                </span>
              }
            >
              Sizing suggestions
            </SectionTitle>
            {sugs === null ? (
              <div style={{ fontSize: 12, color: color.muted }}>
                Pick a mode to illustrate how available cash could be sized. Educational only.
              </div>
            ) : sugs.length === 0 ? (
              <div style={{ fontSize: 12, color: color.muted }}>
                No suggestions (no cash available or no ranked candidates).
              </div>
            ) : (
              sugs.map((sg) => (
                <div key={sg.symbol} style={{ fontSize: 12, fontFamily: font.mono, marginTop: 4 }}>
                  <Badge tone={sg.action === "new" ? color.hue : color.muted}>{sg.action}</Badge>{" "}
                  <b>{sg.symbol}</b> {sg.suggested_qty} sh ≈ {usd(sg.est_cost)} →{" "}
                  {sg.target_weight_pct}%<span style={{ color: color.faint }}> — {sg.reason}</span>
                </div>
              ))
            )}
          </Card>

          <Card pad={space[4]}>
            <SectionTitle
              right={
                <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {commentary?.cached && <Badge>cached</Badge>}
                  <Button
                    variant="ghost"
                    disabled={commentaryBusy}
                    onClick={() => void generateCommentary(!!commentary)}
                  >
                    {commentaryBusy ? "Writing…" : commentary ? "Regenerate" : "Generate"}
                  </Button>
                </span>
              }
            >
              AI advisor review
            </SectionTitle>
            {commentary ? (
              <div style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                {commentary.markdown}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: color.muted }}>
                Generate a plain-English review of this portfolio (cached daily). Educational only.
              </div>
            )}
            {commentary && (
              <div
                style={{ fontSize: 10, color: color.faint, marginTop: 8, fontFamily: font.mono }}
              >
                v{commentary.version} · {new Date(commentary.generated_at).toLocaleString()}
              </div>
            )}
          </Card>
        </>
      )}
    </PageShell>
  );
}
