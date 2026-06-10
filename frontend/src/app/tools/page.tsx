"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";

type JobStat = {
  name: string;
  source: string;
  state: string;
  runs: number;
  errors: number;
  error_rate: number;
  last_run: string | null;
  last_duration_ms: number | null;
  avg_ms: number | null;
  p95_ms: number | null;
  last_error: string | null;
};
type ApiStat = {
  endpoint: string;
  method: string;
  calls: number;
  errors: number;
  error_rate: number;
  last_status: number;
  avg_ms: number | null;
  p95_ms: number | null;
};
type Overview = {
  uptime_seconds: number;
  jobs: JobStat[];
  api: ApiStat[];
  api_totals: { calls: number; errors: number; error_rate: number };
  insights: {
    per_symbol: {
      symbol: string;
      rows: number;
      last_ts: string | null;
      oldest_ts: string | null;
    }[];
    hit_rate: {
      horizon_min: number;
      hits: number;
      total: number;
      pending: number;
      accuracy: number | null;
    }[];
  };
};

const STATE_COLOR: Record<string, string> = {
  running: "#22c55e",
  idle: "#888",
  error: "#ef4444",
  stopped: "#f59e0b",
};

function hz(h: number): string {
  return h >= 1440 ? "1d" : `${h}m`;
}

function ms(v: number | null): string {
  return v === null ? "—" : `${v.toFixed(0)}ms`;
}

function ago(iso: string | null): string {
  if (!iso) return "never";
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

function uptime(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

const th: React.CSSProperties = { textAlign: "left", padding: "9px 12px", color: "#777" };
const td: React.CSSProperties = { padding: "8px 12px", borderTop: "1px solid #1a1a1a" };

export default function ToolsPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async (): Promise<void> => {
    try {
      const res = await apiFetch("/ops/overview");
      if (res.ok) {
        setData((await res.json()) as Overview);
        setError(null);
      } else {
        setError(`Failed to load (${res.status}).`);
      }
    } catch {
      setError("Failed to load ops overview.");
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 10_000); // live refresh every 10s
    return () => clearInterval(id);
  }, [load]);

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
        maxWidth: 980,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 4 }}>
        <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em" }}>Tools</h1>
        {data && (
          <span style={{ color: "#777", fontSize: 12, fontFamily: "var(--font-mono, monospace)" }}>
            uptime {uptime(data.uptime_seconds)} · {data.api_totals.calls} reqs ·{" "}
            <span style={{ color: data.api_totals.errors > 0 ? "#ef4444" : "#22c55e" }}>
              {(data.api_totals.error_rate * 100).toFixed(1)}% errors
            </span>
          </span>
        )}
      </div>
      <p style={{ color: "#555", fontSize: 12, marginBottom: 24 }}>
        Live job status, latencies and API error metrics — refreshes every 10s.
      </p>

      {error && <div style={{ color: "#ef4444", fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {/* Jobs */}
      <h2 style={{ fontSize: 14, color: "#777", fontWeight: 600, marginBottom: 8 }}>Jobs</h2>
      <div style={card}>
        <table style={table}>
          <thead>
            <tr>
              <th style={th}>Job</th>
              <th style={th}>Source</th>
              <th style={th}>State</th>
              <th style={{ ...th, textAlign: "right" }}>Runs</th>
              <th style={{ ...th, textAlign: "right" }}>Errors</th>
              <th style={{ ...th, textAlign: "right" }}>Last</th>
              <th style={{ ...th, textAlign: "right" }}>avg / p95</th>
            </tr>
          </thead>
          <tbody>
            {(data?.jobs ?? []).map((j) => (
              <tr key={j.name}>
                <td style={td} title={j.last_error ?? ""}>
                  {j.name}
                  {j.last_error && <span style={{ color: "#ef4444", marginLeft: 6 }}>⚠</span>}
                </td>
                <td style={{ ...td, color: "#999" }}>{j.source}</td>
                <td style={{ ...td, color: STATE_COLOR[j.state] ?? "#888", fontWeight: 700 }}>
                  {j.state}
                </td>
                <td style={{ ...td, textAlign: "right" }}>{j.runs}</td>
                <td style={{ ...td, textAlign: "right", color: j.errors > 0 ? "#ef4444" : "#888" }}>
                  {j.errors}
                </td>
                <td style={{ ...td, textAlign: "right", color: "#999" }}>{ago(j.last_run)}</td>
                <td style={{ ...td, textAlign: "right", color: "#999" }}>
                  {ms(j.avg_ms)} / {ms(j.p95_ms)}
                </td>
              </tr>
            ))}
            {data && data.jobs.length === 0 && (
              <tr>
                <td style={td} colSpan={7}>
                  No jobs registered yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* API metrics */}
      <h2 style={{ fontSize: 14, color: "#777", fontWeight: 600, margin: "26px 0 8px" }}>
        API endpoints
      </h2>
      <div style={card}>
        <table style={table}>
          <thead>
            <tr>
              <th style={th}>Endpoint</th>
              <th style={th}>Method</th>
              <th style={{ ...th, textAlign: "right" }}>Calls</th>
              <th style={{ ...th, textAlign: "right" }}>Errors</th>
              <th style={{ ...th, textAlign: "right" }}>Err rate</th>
              <th style={{ ...th, textAlign: "right" }}>Last</th>
              <th style={{ ...th, textAlign: "right" }}>avg / p95</th>
            </tr>
          </thead>
          <tbody>
            {(data?.api ?? []).map((a) => (
              <tr key={`${a.method} ${a.endpoint}`}>
                <td style={{ ...td, fontFamily: "var(--font-mono, monospace)" }}>{a.endpoint}</td>
                <td style={{ ...td, color: "#999" }}>{a.method}</td>
                <td style={{ ...td, textAlign: "right" }}>{a.calls}</td>
                <td style={{ ...td, textAlign: "right", color: a.errors > 0 ? "#ef4444" : "#888" }}>
                  {a.errors}
                </td>
                <td
                  style={{
                    ...td,
                    textAlign: "right",
                    color: a.error_rate > 0 ? "#ef4444" : "#888",
                  }}
                >
                  {(a.error_rate * 100).toFixed(0)}%
                </td>
                <td
                  style={{
                    ...td,
                    textAlign: "right",
                    color: a.last_status >= 400 ? "#ef4444" : "#999",
                  }}
                >
                  {a.last_status}
                </td>
                <td style={{ ...td, textAlign: "right", color: "#999" }}>
                  {ms(a.avg_ms)} / {ms(a.p95_ms)}
                </td>
              </tr>
            ))}
            {data && data.api.length === 0 && (
              <tr>
                <td style={td} colSpan={7}>
                  No requests recorded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Signal insights */}
      <h2 style={{ fontSize: 14, color: "#777", fontWeight: 600, margin: "26px 0 8px" }}>
        Signal insights
      </h2>
      <div style={{ ...card, padding: "14px 16px", fontSize: 13 }}>
        <div style={{ marginBottom: 10 }}>
          <span style={{ color: "#777" }}>Backtest hit-rate · </span>
          {(data?.insights.hit_rate ?? []).map((h) => (
            <span key={h.horizon_min} style={{ marginRight: 14 }}>
              {hz(h.horizon_min)}{" "}
              <strong style={{ color: h.accuracy === null ? "#555" : "#e8ff47" }}>
                {h.accuracy === null ? "—" : `${Math.round(h.accuracy * 100)}%`}
              </strong>{" "}
              <span style={{ color: "#666" }}>
                ({h.hits}/{h.total}
                {h.pending ? `, ${h.pending} pending` : ""})
              </span>
            </span>
          ))}
        </div>
        <div style={{ color: "#999", fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>
          {(data?.insights.per_symbol ?? []).map((s) => (
            <span key={s.symbol} style={{ marginRight: 18 }}>
              {s.symbol}: {s.rows} rows
            </span>
          ))}
          <span style={{ color: "#555" }}>
            · rows older than 7 days are purged daily after close
          </span>
        </div>
      </div>
    </main>
  );
}

const card: React.CSSProperties = {
  background: "#111",
  border: "1px solid #222",
  borderRadius: 10,
  overflow: "hidden",
};
const table: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 13,
};
