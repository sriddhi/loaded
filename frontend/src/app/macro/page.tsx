"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { Badge, Button, Card, PageShell, SectionTitle } from "../../components/ui";
import { LineChartView } from "../../components/ui/Chart";
import { chartPalette, color, font, space } from "../../theme/tokens";

type Point = { date: string; value: number };
type Alert = {
  id: string;
  name: string;
  pattern: string;
  series: string[];
  fired: boolean;
  value: number | null;
  detail: string;
};
type Tracker = {
  id: string;
  title: string;
  note: string;
  series: Record<string, Point[]>;
  derived: Record<string, Point[]>;
  alerts: Alert[];
};
type TrackersResp = {
  trackers: Tracker[];
  freshness: { code: string; fetched_at: string | null; fred_updated_at: string | null }[];
  disclaimer: string;
};
type AlertsResp = { alerts: Alert[]; fired: Alert[]; disclaimer: string };

const PATTERN_LABEL: Record<string, string> = {
  threshold: "threshold",
  crossover: "crossover",
  trend: "trend",
  event: "event",
  technical: "technical",
};

// Merge multiple {date,value} series into recharts rows keyed by date.
function mergeSeries(named: Record<string, Point[]>): Record<string, number | string>[] {
  const rows = new Map<string, Record<string, number | string>>();
  for (const [name, points] of Object.entries(named)) {
    for (const p of points) {
      const row = rows.get(p.date) ?? { x: p.date.slice(0, 7) };
      row[name] = p.value;
      rows.set(p.date, row);
    }
  }
  return Array.from(rows.entries())
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([, r]) => r);
}

export default function MacroPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [data, setData] = useState<TrackersResp | null>(null);
  const [alerts, setAlerts] = useState<AlertsResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async (): Promise<void> => {
    try {
      const [tRes, aRes] = await Promise.all([
        apiFetch("/macro/trackers"),
        apiFetch("/macro/alerts"),
      ]);
      setData(tRes.ok ? ((await tRes.json()) as TrackersResp) : null);
      setAlerts(aRes.ok ? ((await aRes.json()) as AlertsResp) : null);
      setError(tRes.ok ? null : `Failed to load trackers (${tRes.status}).`);
    } catch {
      setError("Failed to load macro data.");
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 5 * 60_000);
    return () => clearInterval(id);
  }, [load]);

  async function forceRefresh(): Promise<void> {
    setBusy(true);
    try {
      await apiFetch("/macro/refresh", { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  const fired = alerts?.fired ?? [];

  return (
    <PageShell
      title="Macro"
      maxWidth={1100}
      right={
        <Button variant="ghost" disabled={busy} onClick={() => void forceRefresh()}>
          {busy ? "Refreshing…" : "Refresh from FRED"}
        </Button>
      }
      subtitle="FRED-sourced trackers & the SVM alert playbook — series auto-refresh as FRED updates (daily 6h / weekly 12h / monthly 24h TTLs). Informational only, not financial advice."
    >
      {error && <div style={{ color: color.down, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {/* Fired alerts strip */}
      <Card
        pad={space[4]}
        style={{ marginBottom: space[5] }}
        hue={fired.length ? color.warn : undefined}
      >
        <SectionTitle
          right={
            <span style={{ fontSize: 11, color: color.muted }}>
              {alerts ? `${fired.length} fired of ${alerts.alerts.length} rules` : "…"}
            </span>
          }
        >
          Alerts
        </SectionTitle>
        {fired.length === 0 ? (
          <div style={{ color: color.muted, fontSize: 13 }}>
            No alert rules are currently tripped.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {fired.map((a) => (
              <div
                key={a.id}
                style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}
              >
                <Badge tone={color.warn} filled>
                  {PATTERN_LABEL[a.pattern] ?? a.pattern}
                </Badge>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{a.name}</span>
                <span style={{ fontSize: 12, color: color.muted, fontFamily: font.mono }}>
                  {a.detail}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Tracker cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(480px, 1fr))",
          gap: space[4],
        }}
      >
        {(data?.trackers ?? []).map((t) => {
          const lines = { ...t.derived };
          // Show raw series only when no derived line replaces them (keeps axes sane).
          if (Object.keys(lines).length === 0) {
            for (const [code, pts] of Object.entries(t.series)) lines[code] = pts;
          } else {
            for (const [code, pts] of Object.entries(t.series)) {
              if (["DFF", "DGS2", "ECBDFR", "IRLTLT01DEM156N"].includes(code)) lines[code] = pts;
            }
          }
          const rows = mergeSeries(lines);
          const names = Object.keys(lines);
          const anyData = rows.length > 1;
          return (
            <Card key={t.id} pad={space[4]}>
              <SectionTitle
                right={
                  <span style={{ display: "flex", gap: 6 }}>
                    {t.alerts.map((a) => (
                      <Badge key={a.id} tone={a.fired ? color.warn : color.border} filled={a.fired}>
                        {a.fired ? "FIRED" : "ok"}
                      </Badge>
                    ))}
                  </span>
                }
              >
                {t.title}
              </SectionTitle>
              <div style={{ color: color.muted, fontSize: 12, marginBottom: space[3] }}>
                {t.note}
              </div>
              {anyData ? (
                <LineChartView
                  data={rows}
                  xKey="x"
                  height={180}
                  showAxes
                  series={names.map((n, i) => ({
                    key: n,
                    label: n,
                    color: chartPalette[i % chartPalette.length],
                  }))}
                />
              ) : (
                <div style={{ color: color.faint, fontSize: 13 }}>
                  No data yet — hit “Refresh from FRED”.
                </div>
              )}
              {t.alerts.map((a) => (
                <div
                  key={a.id}
                  style={{ fontSize: 11, color: a.fired ? color.warn : color.faint, marginTop: 6 }}
                >
                  {a.fired ? "▲" : "·"} {a.name} — {a.detail}
                </div>
              ))}
            </Card>
          );
        })}
      </div>

      {/* Freshness footer */}
      {data && data.freshness.length > 0 && (
        <div
          style={{ color: color.faint, fontSize: 10, marginTop: space[5], fontFamily: font.mono }}
        >
          sources:{" "}
          {data.freshness
            .map(
              (f) =>
                `${f.code} @ ${f.fetched_at ? new Date(f.fetched_at).toLocaleString() : "never"}`
            )
            .join(" · ")}
        </div>
      )}
      <div style={{ color: color.faint, fontSize: 10, marginTop: 6 }}>{data?.disclaimer}</div>
    </PageShell>
  );
}
