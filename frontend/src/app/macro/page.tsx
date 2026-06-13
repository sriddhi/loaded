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
  as_of: string | null;
  fired_since: string | null;
  meaning: string;
  impact: string;
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

// "2h ago" / "3d ago" from an ISO timestamp.
function ago(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60_000);
  if (m < 60) return `${Math.max(m, 1)}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

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

function FiredMeta({ a }: { a: Alert }): React.JSX.Element {
  return (
    <span style={{ fontSize: 11, color: color.faint, fontFamily: font.mono }}>
      {a.fired_since ? `fired ${ago(a.fired_since)}` : ""}
      {a.as_of ? ` · data as of ${a.as_of}` : ""}
    </span>
  );
}

function Explainer({ alerts }: { alerts: Alert[] }): React.JSX.Element | null {
  const withInfo = alerts.filter((a) => a.meaning || a.impact);
  if (withInfo.length === 0) return null;
  return (
    <details style={{ marginTop: space[2] }}>
      <summary
        style={{
          cursor: "pointer",
          fontSize: 11,
          color: color.muted,
          userSelect: "none",
        }}
      >
        What this alert means
      </summary>
      {withInfo.map((a) => (
        <div key={a.id} style={{ margin: "6px 0 0 2px", fontSize: 12, lineHeight: 1.5 }}>
          <div style={{ color: color.fg, fontWeight: 600, fontSize: 11 }}>{a.name}</div>
          <div style={{ color: color.muted }}>{a.meaning}</div>
          <div style={{ color: color.faint }}>
            <span style={{ color: a.fired ? color.warn : color.faint, fontWeight: 600 }}>
              Possible impact:{" "}
            </span>
            {a.impact}
          </div>
        </div>
      ))}
    </details>
  );
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
        apiFetch("/macro/trackers?points=600"),
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
      subtitle="FRED-sourced trackers & the SVM alert playbook — series auto-refresh as FRED updates (daily 6h / weekly 12h / monthly 24h TTLs). Drag the strip under a chart to slide its window. Informational only, not financial advice."
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
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {fired.map((a) => (
              <div key={a.id}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
                  <Badge tone={color.warn} filled>
                    {PATTERN_LABEL[a.pattern] ?? a.pattern}
                  </Badge>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{a.name}</span>
                  <span style={{ fontSize: 12, color: color.muted, fontFamily: font.mono }}>
                    {a.detail}
                  </span>
                  <FiredMeta a={a} />
                </div>
                <div style={{ margin: "4px 0 0 2px", fontSize: 12, lineHeight: 1.5 }}>
                  <span style={{ color: color.muted }}>{a.meaning} </span>
                  <span style={{ color: color.faint }}>
                    <span style={{ color: color.warn, fontWeight: 600 }}>Possible impact: </span>
                    {a.impact}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Tracker cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(480px, 100%), 1fr))",
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
                  height={200}
                  showAxes
                  brush
                  brushStart={160}
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
                  {a.fired ? "▲" : "·"} {a.name} — {a.detail} <FiredMeta a={a} />
                </div>
              ))}
              <Explainer alerts={t.alerts} />
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
