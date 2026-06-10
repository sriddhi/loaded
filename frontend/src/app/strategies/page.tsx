"use client";

import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:9000";

const spinnerStyle = `
  @keyframes spin {
    0%   { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  @keyframes pulse-dot {
    0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
    40%            { opacity: 1;   transform: scale(1.1); }
  }
  .spinner {
    display: inline-block;
    width: 13px;
    height: 13px;
    border: 2px solid #555;
    border-top-color: #0a0a0a;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
    margin-right: 7px;
  }
  .pulse-dots span {
    display: inline-block;
    width: 5px;
    height: 5px;
    margin: 0 2px;
    background: #0a0a0a;
    border-radius: 50%;
    animation: pulse-dot 1.2s infinite ease-in-out;
  }
  .pulse-dots span:nth-child(2) { animation-delay: 0.2s; }
  .pulse-dots span:nth-child(3) { animation-delay: 0.4s; }
`;

interface StrategyConfig {
  name: string;
  description: string;
  type: string;
  parameters: Record<string, unknown>;
  filters: Record<string, unknown>;
  signal_logic: string;
}

interface TradeSignal {
  date: string;
  action: "BUY" | "SELL";
  price: number;
  pnl?: number;
}

interface EvalResult {
  strategy_name: string;
  symbol: string;
  period: string;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate: number;
  total_trades: number;
  equity_curve: number[];
  signals: TradeSignal[];
}

const TYPE_COLORS: Record<string, string> = {
  MOMENTUM: "#e8ff47",
  BREAKOUT: "#47d4ff",
  MEAN_REVERSION: "#ff9447",
  CUSTOM: "#c4c4c4",
};

export default function StrategiesPage() {
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<StrategyConfig | null>(null);

  const [symbol, setSymbol] = useState("AAPL");
  const [period, setPeriod] = useState("1y");
  const [capital, setCapital] = useState("10000");
  const [evaluating, setEvaluating] = useState(false);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [result, setResult] = useState<EvalResult | null>(null);

  async function handleGenerate() {
    if (!prompt.trim()) return;
    setGenerating(true);
    setGenError(null);
    setStrategy(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/strategies/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ natural_language_prompt: prompt }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail ?? "Generation failed");
      }
      setStrategy(await res.json());
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setGenerating(false);
    }
  }

  async function handleEvaluate() {
    if (!strategy) return;
    setEvaluating(true);
    setEvalError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/strategies/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_config: strategy,
          symbol,
          period,
          initial_capital: parseFloat(capital) || 10000,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail ?? "Evaluation failed");
      }
      setResult(await res.json());
    } catch (e: unknown) {
      setEvalError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setEvaluating(false);
    }
  }

  const equityData = result?.equity_curve.map((v, i) => ({ i, value: v })) ?? [];
  const positive = (result?.total_return_pct ?? 0) >= 0;

  return (
    <main
      style={{
        background: "#0a0a0a",
        minHeight: "100vh",
        color: "#f5f5f5",
        padding: "48px 32px",
        fontFamily: "inherit",
      }}
    >
      <style>{spinnerStyle}</style>
      <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8, letterSpacing: "-0.5px" }}>
        Strategy Lab
      </h1>
      <p style={{ color: "#666", marginBottom: 40, fontSize: 14 }}>
        Describe a strategy in plain English — Claude generates the config, then backtest it.
      </p>

      {/* ── Generator ── */}
      <section style={{ maxWidth: 720, marginBottom: 40 }}>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe your strategy in plain English... e.g. 'Buy stocks that break above their 20-day SMA on high volume, sell when they fall back below it'"
          rows={4}
          style={{
            width: "100%",
            background: "#111",
            border: genError ? "1px solid #ff4747" : "1px solid #222",
            borderRadius: 8,
            color: "#f5f5f5",
            padding: "14px 16px",
            fontSize: 14,
            resize: "vertical",
            outline: "none",
            boxSizing: "border-box",
            fontFamily: "inherit",
          }}
        />

        {genError && <p style={{ color: "#ff4747", fontSize: 13, marginTop: 8 }}>{genError}</p>}

        <button
          onClick={handleGenerate}
          disabled={generating || !prompt.trim()}
          style={{
            marginTop: 12,
            background: generating || !prompt.trim() ? "#333" : "#e8ff47",
            color: generating || !prompt.trim() ? "#666" : "#0a0a0a",
            border: "none",
            borderRadius: 6,
            padding: "10px 24px",
            fontSize: 14,
            fontWeight: 600,
            cursor: generating || !prompt.trim() ? "not-allowed" : "pointer",
            transition: "background 0.15s",
          }}
        >
          {generating ? (
            <>
              <span className="spinner" />
              Claude is thinking
              <span className="pulse-dots" style={{ marginLeft: 4 }}>
                <span />
                <span />
                <span />
              </span>
            </>
          ) : (
            "Generate Strategy"
          )}
        </button>
      </section>

      {/* ── Strategy Card ── */}
      {strategy && (
        <section
          style={{
            maxWidth: 720,
            marginBottom: 40,
            background: "#111",
            border: "1px solid #222",
            borderRadius: 10,
            padding: 24,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{strategy.name}</h2>
            <span
              style={{
                background: TYPE_COLORS[strategy.type] ?? "#444",
                color: "#0a0a0a",
                fontSize: 11,
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: 4,
                fontFamily: "monospace",
              }}
            >
              {strategy.type}
            </span>
          </div>
          <p style={{ color: "#aaa", fontSize: 14, marginBottom: 16 }}>{strategy.description}</p>

          <p style={{ fontSize: 13, color: "#f5f5f5", marginBottom: 16 }}>
            <span style={{ color: "#666", marginRight: 8 }}>Signal logic:</span>
            {strategy.signal_logic}
          </p>

          {Object.keys(strategy.parameters).length > 0 && (
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 13,
                fontFamily: "monospace",
              }}
            >
              <thead>
                <tr>
                  <th
                    style={{ textAlign: "left", color: "#555", fontWeight: 500, paddingBottom: 6 }}
                  >
                    Parameter
                  </th>
                  <th
                    style={{ textAlign: "left", color: "#555", fontWeight: 500, paddingBottom: 6 }}
                  >
                    Value
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(strategy.parameters).map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ padding: "4px 0", color: "#888" }}>{k}</td>
                    <td style={{ padding: "4px 0", color: "#e8ff47" }}>{String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {/* ── Evaluator ── */}
      {strategy && (
        <section style={{ maxWidth: 720, marginBottom: 40 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Backtest</h2>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
            <div>
              <label style={{ fontSize: 12, color: "#666", display: "block", marginBottom: 4 }}>
                Symbol
              </label>
              <input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                style={{
                  background: "#111",
                  border: "1px solid #222",
                  borderRadius: 6,
                  color: "#f5f5f5",
                  padding: "8px 12px",
                  fontSize: 14,
                  width: 100,
                  fontFamily: "monospace",
                  outline: "none",
                }}
              />
            </div>
            <div>
              <label style={{ fontSize: 12, color: "#666", display: "block", marginBottom: 4 }}>
                Period
              </label>
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                style={{
                  background: "#111",
                  border: "1px solid #222",
                  borderRadius: 6,
                  color: "#f5f5f5",
                  padding: "8px 12px",
                  fontSize: 14,
                  fontFamily: "monospace",
                  outline: "none",
                }}
              >
                {["3mo", "6mo", "1y", "2y"].map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 12, color: "#666", display: "block", marginBottom: 4 }}>
                Capital ($)
              </label>
              <input
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                type="number"
                style={{
                  background: "#111",
                  border: "1px solid #222",
                  borderRadius: 6,
                  color: "#f5f5f5",
                  padding: "8px 12px",
                  fontSize: 14,
                  width: 120,
                  fontFamily: "monospace",
                  outline: "none",
                }}
              />
            </div>
          </div>

          <button
            onClick={handleEvaluate}
            disabled={evaluating}
            style={{
              background: evaluating ? "#333" : "#e8ff47",
              color: evaluating ? "#666" : "#0a0a0a",
              border: "none",
              borderRadius: 6,
              padding: "10px 24px",
              fontSize: 14,
              fontWeight: 600,
              cursor: evaluating ? "not-allowed" : "pointer",
            }}
          >
            {evaluating ? (
              <>
                <span className="spinner" />
                Running backtest
                <span className="pulse-dots" style={{ marginLeft: 4 }}>
                  <span />
                  <span />
                  <span />
                </span>
              </>
            ) : (
              "Run Backtest"
            )}
          </button>

          {evalError && (
            <p style={{ color: "#ff4747", fontSize: 13, marginTop: 12 }}>{evalError}</p>
          )}
        </section>
      )}

      {/* ── Results ── */}
      {result && (
        <section style={{ maxWidth: 720 }}>
          {/* Metric cards */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 12,
              marginBottom: 32,
            }}
          >
            {[
              {
                label: "Total Return",
                value: `${result.total_return_pct.toFixed(2)}%`,
                highlight: positive,
              },
              {
                label: "Sharpe Ratio",
                value: result.sharpe_ratio.toFixed(2),
                highlight: result.sharpe_ratio > 1,
              },
              {
                label: "Max Drawdown",
                value: `${result.max_drawdown_pct.toFixed(2)}%`,
                highlight: false,
                negative: true,
              },
              {
                label: "Win Rate",
                value: `${result.win_rate.toFixed(1)}%`,
                highlight: result.win_rate > 50,
              },
            ].map(({ label, value, highlight, negative }) => (
              <div
                key={label}
                style={{
                  background: "#111",
                  border: "1px solid #222",
                  borderRadius: 8,
                  padding: "16px 14px",
                }}
              >
                <div style={{ fontSize: 11, color: "#555", marginBottom: 6 }}>{label}</div>
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    fontFamily: "monospace",
                    color: negative ? "#ff4747" : highlight ? "#e8ff47" : "#f5f5f5",
                  }}
                >
                  {value}
                </div>
              </div>
            ))}
          </div>

          {/* Equity curve */}
          <div
            style={{
              background: "#111",
              border: "1px solid #222",
              borderRadius: 10,
              padding: 20,
              marginBottom: 24,
            }}
          >
            <div style={{ fontSize: 13, color: "#555", marginBottom: 12 }}>Equity Curve</div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={equityData}>
                <XAxis dataKey="i" hide />
                <YAxis
                  domain={["auto", "auto"]}
                  tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                  style={{ fontSize: 11, fill: "#555", fontFamily: "monospace" }}
                  width={55}
                />
                <Tooltip
                  formatter={(v: number) => [`$${v.toFixed(2)}`, "Equity"]}
                  contentStyle={{
                    background: "#1a1a1a",
                    border: "1px solid #333",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  labelStyle={{ display: "none" }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={positive ? "#e8ff47" : "#ff4747"}
                  dot={false}
                  strokeWidth={1.5}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Trade log */}
          {result.signals.length > 0 && (
            <div
              style={{
                background: "#111",
                border: "1px solid #222",
                borderRadius: 10,
                padding: 20,
              }}
            >
              <div style={{ fontSize: 13, color: "#555", marginBottom: 12 }}>
                Trade Log — {result.total_trades} trades
              </div>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: 13,
                  fontFamily: "monospace",
                }}
              >
                <thead>
                  <tr>
                    {["Date", "Action", "Price", "P&L"].map((h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: "left",
                          color: "#444",
                          fontWeight: 500,
                          paddingBottom: 8,
                          fontSize: 11,
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.signals.map((s, i) => (
                    <tr key={i} style={{ borderTop: "1px solid #1a1a1a" }}>
                      <td style={{ padding: "6px 0", color: "#666" }}>{s.date}</td>
                      <td
                        style={{
                          padding: "6px 0",
                          color: s.action === "BUY" ? "#e8ff47" : "#ff9447",
                          fontWeight: 600,
                        }}
                      >
                        {s.action}
                      </td>
                      <td style={{ padding: "6px 0", color: "#f5f5f5" }}>${s.price.toFixed(2)}</td>
                      <td
                        style={{
                          padding: "6px 0",
                          color: s.pnl == null ? "#444" : s.pnl >= 0 ? "#e8ff47" : "#ff4747",
                        }}
                      >
                        {s.pnl != null ? `${s.pnl >= 0 ? "+" : ""}$${s.pnl.toFixed(2)}` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
