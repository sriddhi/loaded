"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { Card, PageShell, SectionTitle, Stat, Tabs } from "../../components/ui";
import { color, font, space } from "../../theme/tokens";

type Tally = {
  decisions: number;
  right: number;
  wrong: number;
  win_rate_pct: number | null;
  total_upside_usd: number;
  avg_per_trade_usd: number | null;
};
type Trade = {
  strategy: string;
  symbol?: string;
  contract: string;
  side: string;
  strike: number;
  expiry: string;
  underlying_px?: number;
  spy?: number;
  entry: number;
  exit?: number;
  pnl: number;
  right: boolean;
  exit_reason?: string;
  opened_at: string;
  closed_at?: string;
};
type Report = {
  date?: string;
  account: string;
  underlyings?: string[];
  started_pt: string;
  ends_pt: string;
  updated: string;
  by_strategy: Record<string, Tally>;
  by_symbol?: Record<string, Tally>;
  combined: Tally;
  trades: Trade[];
};
type ReportListItem = { date: string; underlyings: string[]; combined: Tally };

const EXIT_COLOR: Record<string, string> = {
  take_profit: color.up,
  stop_loss: color.down,
  time_stop: color.muted,
  end_of_window: color.warn,
};

function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}

function TallyCards({ t }: { t: Tally }): React.JSX.Element {
  return (
    <div style={{ display: "flex", gap: space[5], flexWrap: "wrap" }}>
      <Stat label="Decisions" value={t.decisions} />
      <Stat label="Right" value={t.right} tone={color.up} />
      <Stat label="Wrong" value={t.wrong} tone={t.wrong > 0 ? color.down : color.muted} />
      <Stat
        label="Win rate"
        value={t.win_rate_pct === null ? "—" : `${t.win_rate_pct}%`}
        tone={t.win_rate_pct !== null && t.win_rate_pct >= 50 ? color.up : color.muted}
      />
      <Stat
        label="Total upside"
        value={money(t.total_upside_usd)}
        tone={t.total_upside_usd >= 0 ? color.up : color.down}
        sub={t.avg_per_trade_usd !== null ? `avg ${money(t.avg_per_trade_usd)}/trade` : undefined}
      />
    </div>
  );
}

export default function PaperPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [days, setDays] = useState<ReportListItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const loadList = useCallback(async (): Promise<void> => {
    try {
      const res = await apiFetch("/ops/paper/reports");
      if (!res.ok) {
        setError(`Failed to list reports (${res.status}).`);
        setDays([]);
        return;
      }
      const list = ((await res.json()) as { reports: ReportListItem[] }).reports;
      setDays(list);
      setSelected((cur) => cur ?? list[0]?.date ?? null);
      setError(null);
    } catch {
      setError("Failed to list reports.");
      setDays([]);
    }
  }, []);

  const loadDay = useCallback(async (date: string): Promise<void> => {
    try {
      const res = await apiFetch(`/ops/paper/reports/${date}`);
      setReport(res.ok ? ((await res.json()) as Report) : null);
    } catch {
      setReport(null);
    }
  }, []);

  useEffect(() => {
    void loadList();
    const id = setInterval(() => void loadList(), 60_000);
    return () => clearInterval(id);
  }, [loadList]);

  useEffect(() => {
    if (selected) void loadDay(selected);
  }, [selected, loadDay]);

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  return (
    <PageShell
      title="Paper Trading"
      maxWidth={1000}
      subtitle="Simulated 0-3 DTE option decisions per asset — Alpaca PAPER account, long options only, 1 contract per decision. Per-day archives. Not financial advice."
    >
      {error && <div style={{ color: color.down, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {days === null ? (
        <div style={{ color: "#8a8a8a", fontSize: 13 }}>Loading reports…</div>
      ) : days.length === 0 ? (
        <Card pad={space[5]}>
          <div style={{ color: color.muted, fontSize: 14, lineHeight: 1.6 }}>
            No paper-trading reports yet. The job runs every market day from the 9:30 ET open until
            1:00pm PT and archives one report per session — the first one will appear here after the
            next open.
          </div>
        </Card>
      ) : (
        <>
          <div style={{ marginBottom: space[4] }}>
            <Tabs
              options={days.map((d) => d.date)}
              value={selected ?? ""}
              onChange={(v) => setSelected(v)}
            />
          </div>

          {report && (
            <>
              <Card pad={space[4]} style={{ marginBottom: space[4] }}>
                <SectionTitle
                  right={
                    <span style={{ fontSize: 11, color: color.faint, fontFamily: font.mono }}>
                      {report.started_pt} → {report.ends_pt} ·{" "}
                      {(report.underlyings ?? []).join(" · ")}
                    </span>
                  }
                >
                  Combined
                </SectionTitle>
                <TallyCards t={report.combined} />
              </Card>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                  gap: space[4],
                  marginBottom: space[4],
                }}
              >
                {Object.entries(report.by_strategy ?? {}).map(([name, t]) => (
                  <Card key={name} pad={space[4]}>
                    <SectionTitle>strategy · {name}</SectionTitle>
                    <TallyCards t={t} />
                  </Card>
                ))}
                {Object.entries(report.by_symbol ?? {}).map(([sym, t]) => (
                  <Card key={sym} pad={space[4]}>
                    <SectionTitle>asset · {sym}</SectionTitle>
                    <TallyCards t={t} />
                  </Card>
                ))}
              </div>

              <SectionTitle>Trades</SectionTitle>
              <Card pad={0} style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 12,
                    fontFamily: font.mono,
                  }}
                >
                  <thead>
                    <tr style={{ color: color.muted }}>
                      {[
                        "Opened",
                        "Asset",
                        "Strategy",
                        "Side",
                        "Contract",
                        "Entry",
                        "Exit",
                        "P&L",
                        "Exit reason",
                        "",
                      ].map((h) => (
                        <th
                          key={h}
                          style={{ textAlign: "left", padding: "9px 12px", whiteSpace: "nowrap" }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {report.trades.map((t, i) => (
                      <tr key={i} style={{ borderTop: `1px solid ${color.border}` }}>
                        <td style={{ padding: "7px 12px", color: color.muted }}>
                          {new Date(t.opened_at).toLocaleTimeString()}
                        </td>
                        <td style={{ padding: "7px 12px" }}>{t.symbol ?? "SPY"}</td>
                        <td style={{ padding: "7px 12px", color: color.muted }}>{t.strategy}</td>
                        <td
                          style={{
                            padding: "7px 12px",
                            color: t.side === "CALL" ? color.up : color.down,
                            fontWeight: 700,
                          }}
                        >
                          {t.side}
                        </td>
                        <td style={{ padding: "7px 12px", color: color.muted }}>{t.contract}</td>
                        <td style={{ padding: "7px 12px" }}>${t.entry.toFixed(2)}</td>
                        <td style={{ padding: "7px 12px" }}>
                          {t.exit !== undefined ? `$${t.exit.toFixed(2)}` : "—"}
                        </td>
                        <td
                          style={{
                            padding: "7px 12px",
                            color: t.pnl >= 0 ? color.up : color.down,
                            fontWeight: 700,
                          }}
                        >
                          {money(t.pnl)}
                        </td>
                        <td
                          style={{
                            padding: "7px 12px",
                            color: EXIT_COLOR[t.exit_reason ?? ""] ?? color.muted,
                          }}
                        >
                          {t.exit_reason ?? "—"}
                        </td>
                        <td style={{ padding: "7px 12px" }}>{t.right ? "✓" : "✗"}</td>
                      </tr>
                    ))}
                    {report.trades.length === 0 && (
                      <tr>
                        <td colSpan={10} style={{ padding: 14, color: color.faint }}>
                          No trades this session — the strategies stayed inside their thresholds.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </Card>
              <div style={{ color: color.faint, fontSize: 10, marginTop: 8 }}>
                {report.account} · updated {new Date(report.updated).toLocaleTimeString()}
              </div>
            </>
          )}
        </>
      )}
    </PageShell>
  );
}
