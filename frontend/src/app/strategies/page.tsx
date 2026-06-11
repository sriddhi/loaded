"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────
type StrategyConfig = {
  name: string;
  description: string;
  type: string;
  parameters: Record<string, unknown>;
  filters: Record<string, unknown>;
  signal_logic: string;
};
type Artifact = { type: "strategy" | "market_data" | "backtest" | "text"; data: unknown };
type ChatMessage = { role: string; content: string };
type RunConfig = {
  schedule_kind: string;
  interval_minutes: number;
  run_at_et: string;
  backtest_enabled: boolean;
  backtest_periods: string[];
  backtest_symbol: string | null;
  paper_qty: number;
  max_positions: number;
};
type Saved = {
  id: number;
  name: string;
  config: StrategyConfig;
  mode: string;
  enabled: boolean;
  symbols: string[];
  run_config: Partial<RunConfig>;
  last_run_at: string | null;
};
type Run = {
  id: number;
  run_type: string;
  status: string;
  source: string;
  period: string | null;
  metrics: Record<string, unknown> | null;
  detail: string | null;
  duration_ms: number | null;
  created_at: string;
};

const MODES = ["backtest", "signal", "paper"];
const PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y"];
const ACCENT = "#e8ff47";

const card: React.CSSProperties = {
  background: "#111",
  border: "1px solid #222",
  borderRadius: 10,
};

// ── Right-panel artifact renderers ────────────────────────────────────────────
function MarketDataView({ data }: { data: Record<string, unknown> }): React.JSX.Element {
  const rows = (data.rows as Record<string, unknown>[]) ?? null;
  const gainers = (data.gainers as Record<string, unknown>[]) ?? null;
  const losers = (data.losers as Record<string, unknown>[]) ?? null;
  const fundamentals = data.fundamentals as Record<string, unknown> | undefined;
  const renderTable = (items: Record<string, unknown>[]): React.JSX.Element => (
    <table
      style={{ width: "100%", fontSize: 13, fontFamily: "monospace", borderCollapse: "collapse" }}
    >
      <tbody>
        {items.map((r, i) => (
          <tr key={i} style={{ borderTop: "1px solid #1a1a1a" }}>
            {Object.entries(r).map(([k, v]) => (
              <td key={k} style={{ padding: "6px 10px", color: k === "symbol" ? "#fff" : "#aaa" }}>
                {String(v)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <div>
      <h3 style={{ fontSize: 15, marginBottom: 10 }}>{String(data.title ?? "Market data")}</h3>
      {rows && renderTable(rows)}
      {gainers && (
        <>
          <div style={{ color: "#22c55e", fontSize: 12, margin: "10px 0 4px" }}>Gainers</div>
          {renderTable(gainers)}
        </>
      )}
      {losers && (
        <>
          <div style={{ color: "#ef4444", fontSize: 12, margin: "10px 0 4px" }}>Losers</div>
          {renderTable(losers)}
        </>
      )}
      {fundamentals && (
        <pre style={{ fontSize: 12, color: "#aaa", whiteSpace: "pre-wrap", marginTop: 10 }}>
          {JSON.stringify(fundamentals, null, 2)}
        </pre>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  good,
}: {
  label: string;
  value: string;
  good?: boolean;
}): React.JSX.Element {
  return (
    <div>
      <div style={{ color: "#666", fontSize: 11 }}>{label}</div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: good === undefined ? "#fff" : good ? "#22c55e" : "#ef4444",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function BacktestView({ data }: { data: Record<string, unknown> }): React.JSX.Element {
  const results = (data.results as Record<string, unknown>[]) ?? [];
  return (
    <div>
      <h3 style={{ fontSize: 15, marginBottom: 10 }}>Backtest results</h3>
      {results.map((r, i) => {
        const m = (r.metrics as Record<string, number>) ?? {};
        const curve = ((r.equity_curve as number[]) ?? []).map((v, idx) => ({ i: idx, v }));
        if (r.status === "error")
          return (
            <div key={i} style={{ color: "#ef4444", fontSize: 13, marginBottom: 10 }}>
              {String(r.period)}: {String(r.detail)}
            </div>
          );
        return (
          <div key={i} style={{ ...card, padding: 14, marginBottom: 12 }}>
            <div style={{ fontSize: 13, color: "#777", marginBottom: 8 }}>
              {String(r.period)} · {String(m.symbol ?? "")}
            </div>
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginBottom: 10 }}>
              <Metric
                label="Return"
                value={`${(m.total_return_pct ?? 0).toFixed(2)}%`}
                good={(m.total_return_pct ?? 0) >= 0}
              />
              <Metric label="Sharpe" value={(m.sharpe_ratio ?? 0).toFixed(2)} />
              <Metric label="Max DD" value={`${(m.max_drawdown_pct ?? 0).toFixed(2)}%`} />
              <Metric label="Win rate" value={`${((m.win_rate ?? 0) * 100).toFixed(0)}%`} />
              <Metric label="Trades" value={String(m.total_trades ?? 0)} />
            </div>
            {curve.length > 1 && (
              <ResponsiveContainer width="100%" height={140}>
                <LineChart data={curve}>
                  <XAxis dataKey="i" hide />
                  <YAxis domain={["auto", "auto"]} hide />
                  <Tooltip contentStyle={{ background: "#111", border: "1px solid #333" }} />
                  <Line dataKey="v" stroke={ACCENT} dot={false} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function StrategiesPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [draft, setDraft] = useState<StrategyConfig | null>(null);
  const [mode, setMode] = useState("backtest");
  const [scheduleKind, setScheduleKind] = useState("manual");
  const [intervalMin, setIntervalMin] = useState(60);
  const [runAtEt, setRunAtEt] = useState("16:05");
  const [symbol, setSymbol] = useState("SPY");
  const [periods, setPeriods] = useState<string[]>(["1y"]);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [runsFor, setRunsFor] = useState<{ id: number; runs: Run[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const loadSaved = useCallback(async (): Promise<void> => {
    const res = await apiFetch("/strategies/");
    if (res.ok) setSaved((await res.json()) as Saved[]);
  }, []);

  useEffect(() => {
    void loadSaved();
  }, [loadSaved]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async (): Promise<void> => {
    const text = input.trim();
    if (!text || busy) return;
    const next = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch("/strategies/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: next }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `Chat failed (${res.status})`);
      }
      const data = (await res.json()) as { reply: string; artifact: Artifact };
      setMessages([...next, { role: "assistant", content: data.reply }]);
      setArtifact(data.artifact);
      if (data.artifact?.type === "strategy") {
        setDraft(data.artifact.data as StrategyConfig);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chat failed.");
    } finally {
      setBusy(false);
    }
  }, [input, busy, messages]);

  const saveStrategy = useCallback(async (): Promise<void> => {
    if (!draft) return;
    setError(null);
    const run_config: RunConfig = {
      schedule_kind: scheduleKind,
      interval_minutes: intervalMin,
      run_at_et: runAtEt,
      backtest_enabled: true,
      backtest_periods: periods,
      backtest_symbol: symbol,
      paper_qty: 1,
      max_positions: 1,
    };
    const res = await apiFetch("/strategies/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: draft, mode, enabled: false, symbols: [symbol], run_config }),
    });
    if (res.ok) {
      setDraft(null);
      setArtifact({ type: "text", data: "Saved. Configure it below." });
      await loadSaved();
    } else {
      setError(`Save failed (${res.status}).`);
    }
  }, [draft, mode, scheduleKind, intervalMin, runAtEt, symbol, periods, loadSaved]);

  const toggleEnabled = useCallback(
    async (s: Saved): Promise<void> => {
      await apiFetch(`/strategies/${s.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !s.enabled }),
      });
      await loadSaved();
    },
    [loadSaved]
  );

  const backtestSaved = useCallback(
    async (s: Saved): Promise<void> => {
      setBusy(true);
      setError(null);
      try {
        const res = await apiFetch(`/strategies/${s.id}/backtest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            periods: s.run_config.backtest_periods ?? ["1y"],
            symbol: s.symbols[0] ?? null,
          }),
        });
        if (res.ok) {
          const data = (await res.json()) as Record<string, unknown>;
          setArtifact({ type: "backtest", data });
        } else setError(`Backtest failed (${res.status}).`);
      } finally {
        setBusy(false);
        await loadSaved();
      }
    },
    [loadSaved]
  );

  const viewRuns = useCallback(async (s: Saved): Promise<void> => {
    const res = await apiFetch(`/strategies/${s.id}/runs`);
    if (res.ok) setRunsFor({ id: s.id, runs: (await res.json()) as Run[] });
  }, []);

  const removeStrategy = useCallback(
    async (s: Saved): Promise<void> => {
      await apiFetch(`/strategies/${s.id}`, { method: "DELETE" });
      setRunsFor((cur) => (cur?.id === s.id ? null : cur));
      await loadSaved();
    },
    [loadSaved]
  );

  if (authLoading || !user) return <main style={{ background: "#0a0a0a", minHeight: "100vh" }} />;

  return (
    <main
      style={{
        background: "#0a0a0a",
        color: "#f5f5f5",
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        padding: "20px 24px",
        boxSizing: "border-box",
      }}
    >
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 2 }}>Strategy Lab</h1>
      <p style={{ color: "#555", fontSize: 12, marginBottom: 14 }}>
        Chat to explore the market and build strategies. Save them, schedule runs, backtest, and
        (paper) trade. Paper/indicator tool — not financial advice.
      </p>
      {error && <div style={{ color: "#ef4444", fontSize: 13, marginBottom: 8 }}>{error}</div>}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          flex: 1,
          minHeight: 0,
        }}
      >
        {/* ── Left: chat ── */}
        <div style={{ ...card, display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
            {messages.length === 0 && (
              <div style={{ color: "#555", fontSize: 13 }}>
                Try: “which was the most traded equity today” or “buy SPY when it breaks the 20-day
                high on 1.5× volume”.
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ marginBottom: 14 }}>
                <div
                  style={{
                    color: m.role === "user" ? ACCENT : "#777",
                    fontSize: 11,
                    marginBottom: 3,
                  }}
                >
                  {m.role === "user" ? "You" : "Assistant"}
                </div>
                <div
                  style={{ fontSize: 14, color: "#eee", whiteSpace: "pre-wrap", lineHeight: 1.5 }}
                >
                  {m.content}
                </div>
              </div>
            ))}
            {busy && <div style={{ color: "#777", fontSize: 13 }}>…thinking</div>}
            <div ref={chatEnd} />
          </div>
          <div style={{ borderTop: "1px solid #222", padding: 12, display: "flex", gap: 8 }}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder="Message…"
              rows={2}
              style={{
                flex: 1,
                background: "#0a0a0a",
                color: "#eee",
                border: "1px solid #2a2a2a",
                borderRadius: 6,
                padding: 8,
                fontFamily: "inherit",
                fontSize: 13,
                resize: "none",
              }}
            />
            <button
              onClick={() => void send()}
              disabled={busy}
              style={{
                background: ACCENT,
                color: "#0a0a0a",
                border: "none",
                borderRadius: 6,
                padding: "0 16px",
                fontWeight: 700,
                cursor: busy ? "default" : "pointer",
                opacity: busy ? 0.6 : 1,
              }}
            >
              Send
            </button>
          </div>
        </div>

        {/* ── Right: artifact / details ── */}
        <div style={{ ...card, overflowY: "auto", padding: 16, minHeight: 0 }}>
          {(!artifact || artifact.type === "text") && (
            <div style={{ color: "#555", fontSize: 13, lineHeight: 1.6 }}>
              Structured results show up here — ask me to <strong>build a strategy</strong> (you’ll
              get an editable config you can save &amp; backtest), or{" "}
              <strong>pull market data</strong>. The conversation itself stays on the left.
            </div>
          )}
          {artifact?.type === "market_data" && (
            <MarketDataView data={artifact.data as Record<string, unknown>} />
          )}
          {artifact?.type === "backtest" && (
            <BacktestView data={artifact.data as Record<string, unknown>} />
          )}

          {artifact?.type === "strategy" && draft && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <h3 style={{ fontSize: 16 }}>{draft.name}</h3>
                <span
                  style={{
                    fontSize: 10,
                    padding: "2px 8px",
                    border: `1px solid ${ACCENT}`,
                    borderRadius: 4,
                    color: ACCENT,
                  }}
                >
                  {draft.type}
                </span>
              </div>
              <p style={{ color: "#aaa", fontSize: 13, marginBottom: 8 }}>{draft.description}</p>
              <div style={{ color: "#888", fontSize: 12, marginBottom: 4 }}>Signal logic</div>
              <p style={{ color: "#ccc", fontSize: 13, marginBottom: 10 }}>{draft.signal_logic}</p>
              <pre
                style={{
                  fontSize: 12,
                  color: "#999",
                  background: "#0a0a0a",
                  padding: 10,
                  borderRadius: 6,
                  overflowX: "auto",
                }}
              >
                {JSON.stringify({ parameters: draft.parameters, filters: draft.filters }, null, 2)}
              </pre>

              {/* Run config */}
              <div style={{ borderTop: "1px solid #222", marginTop: 14, paddingTop: 12 }}>
                <div style={{ color: "#888", fontSize: 12, marginBottom: 8 }}>
                  When &amp; how to run
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    flexWrap: "wrap",
                    alignItems: "center",
                    fontSize: 13,
                  }}
                >
                  <label>
                    Mode{" "}
                    <select value={mode} onChange={(e) => setMode(e.target.value)} style={sel}>
                      {MODES.map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Symbol{" "}
                    <input
                      value={symbol}
                      onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                      style={{ ...sel, width: 70 }}
                    />
                  </label>
                  <label>
                    Schedule{" "}
                    <select
                      value={scheduleKind}
                      onChange={(e) => setScheduleKind(e.target.value)}
                      style={sel}
                    >
                      <option value="manual">manual</option>
                      <option value="interval">interval</option>
                      <option value="daily">daily</option>
                    </select>
                  </label>
                  {scheduleKind === "interval" && (
                    <label>
                      every{" "}
                      <input
                        type="number"
                        value={intervalMin}
                        onChange={(e) => setIntervalMin(Number(e.target.value))}
                        style={{ ...sel, width: 60 }}
                      />
                      min
                    </label>
                  )}
                  {scheduleKind === "daily" && (
                    <label>
                      at(ET){" "}
                      <input
                        value={runAtEt}
                        onChange={(e) => setRunAtEt(e.target.value)}
                        style={{ ...sel, width: 70 }}
                      />
                    </label>
                  )}
                </div>
                <div style={{ marginTop: 8, fontSize: 13 }}>
                  Backtest periods:{" "}
                  {PERIODS.map((p) => (
                    <button
                      key={p}
                      onClick={() =>
                        setPeriods((cur) =>
                          cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]
                        )
                      }
                      style={{
                        marginRight: 6,
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 12,
                        cursor: "pointer",
                        background: periods.includes(p) ? ACCENT : "#161616",
                        color: periods.includes(p) ? "#0a0a0a" : "#999",
                        border: "1px solid #2a2a2a",
                      }}
                    >
                      {p}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => void saveStrategy()}
                  style={{
                    marginTop: 14,
                    background: ACCENT,
                    color: "#0a0a0a",
                    border: "none",
                    borderRadius: 6,
                    padding: "8px 18px",
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Save strategy
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Saved strategies ── */}
      <div style={{ marginTop: 14, maxHeight: "30vh", overflowY: "auto" }}>
        <h2 style={{ fontSize: 13, color: "#777", marginBottom: 8 }}>Saved strategies</h2>
        {saved.length === 0 && (
          <div style={{ color: "#555", fontSize: 13 }}>
            None yet — build one in chat and save it.
          </div>
        )}
        {saved.map((s) => (
          <div key={s.id}>
            <div
              style={{
                ...card,
                padding: "10px 14px",
                marginBottom: 8,
                display: "flex",
                alignItems: "center",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <button
                onClick={() => void toggleEnabled(s)}
                title={s.enabled ? "Disable" : "Enable"}
                style={{
                  width: 44,
                  height: 22,
                  borderRadius: 11,
                  border: "none",
                  cursor: "pointer",
                  background: s.enabled ? "#22c55e" : "#333",
                  position: "relative",
                }}
              >
                <span
                  style={{
                    position: "absolute",
                    top: 2,
                    left: s.enabled ? 24 : 2,
                    width: 18,
                    height: 18,
                    borderRadius: "50%",
                    background: "#fff",
                    transition: "left .15s",
                  }}
                />
              </button>
              <strong style={{ fontSize: 14 }}>{s.name}</strong>
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 7px",
                  border: "1px solid #2a2a2a",
                  borderRadius: 4,
                  color: "#aaa",
                }}
              >
                {s.mode}
              </span>
              <span style={{ fontSize: 11, color: "#666" }}>{s.symbols.join(", ") || "—"}</span>
              <span style={{ fontSize: 11, color: "#555" }}>
                {s.last_run_at
                  ? `last run ${new Date(s.last_run_at).toLocaleString()}`
                  : "never run"}
              </span>
              <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <button onClick={() => void backtestSaved(s)} style={btn}>
                  Backtest
                </button>
                <button onClick={() => void viewRuns(s)} style={btn}>
                  Runs
                </button>
                <button onClick={() => void removeStrategy(s)} style={{ ...btn, color: "#ef4444" }}>
                  Delete
                </button>
              </div>
            </div>
            {runsFor?.id === s.id && (
              <div style={{ ...card, padding: 12, marginBottom: 8 }}>
                <div style={{ color: "#777", fontSize: 12, marginBottom: 6 }}>
                  Run history (observability)
                </div>
                <table
                  style={{
                    width: "100%",
                    fontSize: 12,
                    fontFamily: "monospace",
                    borderCollapse: "collapse",
                  }}
                >
                  <thead>
                    <tr style={{ color: "#777" }}>
                      {["time", "type", "status", "src", "period", "ms", "detail"].map((h) => (
                        <th key={h} style={{ textAlign: "left", padding: "4px 8px" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {runsFor.runs.map((r) => (
                      <tr key={r.id} style={{ borderTop: "1px solid #1a1a1a" }}>
                        <td style={tdc}>{new Date(r.created_at).toLocaleTimeString()}</td>
                        <td style={tdc}>{r.run_type}</td>
                        <td style={{ ...tdc, color: r.status === "ok" ? "#22c55e" : "#ef4444" }}>
                          {r.status}
                        </td>
                        <td style={tdc}>{r.source}</td>
                        <td style={tdc}>{r.period ?? "—"}</td>
                        <td style={tdc}>{r.duration_ms ?? "—"}</td>
                        <td style={{ ...tdc, color: "#888" }}>
                          {r.metrics
                            ? `ret ${(r.metrics.total_return_pct as number)?.toFixed?.(1) ?? "—"}%`
                            : (r.detail ?? "")}
                        </td>
                      </tr>
                    ))}
                    {runsFor.runs.length === 0 && (
                      <tr>
                        <td style={tdc} colSpan={7}>
                          No runs yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}

const sel: React.CSSProperties = {
  background: "#0a0a0a",
  color: "#eee",
  border: "1px solid #2a2a2a",
  borderRadius: 4,
  padding: "3px 6px",
  marginLeft: 4,
};
const btn: React.CSSProperties = {
  background: "#161616",
  color: "#bbb",
  border: "1px solid #2a2a2a",
  borderRadius: 5,
  padding: "4px 12px",
  fontSize: 12,
  cursor: "pointer",
};
const tdc: React.CSSProperties = { padding: "4px 8px" };
