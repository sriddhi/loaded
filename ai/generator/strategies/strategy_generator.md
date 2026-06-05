# Strategy Generator Prompt

**Feature:** Strategy Generator + Evaluator  
**Version:** 1.0  
**Target:** `backend/app/strategies/` + `frontend/src/app/strategies/`

---

## Context

You are building the Strategy Generator + Evaluator feature for **Loaded** — an institution-grade trading platform for retail traders.

Loaded stack:
- Backend: FastAPI + asyncpg + PostgreSQL (no ORM), running in Docker at `localhost:8000`
- Frontend: Next.js 14 App Router (TypeScript), running in Docker at `localhost:3000`
- Design: near-black `#0a0a0a`, off-white `#f5f5f5`, electric yellow `#e8ff47`, monospace fonts
- Market data: yfinance for OHLCV history, Alpaca for live/paper trading

---

## What to Build

### 1. Backend — `backend/app/strategies/`

Create the following files:

#### `models.py`
Define Pydantic models:
- `StrategyConfig` — name, description, type (enum: MOMENTUM, BREAKOUT, MEAN_REVERSION, CUSTOM), parameters (dict), filters (dict), signal_logic (str description)
- `GenerateRequest` — natural_language_prompt (str), context (optional dict)
- `EvalRequest` — strategy_config (StrategyConfig), symbol (str), period (str, default "1y"), initial_capital (float, default 10000)
- `EvalResult` — strategy_name, symbol, period, total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate, total_trades, equity_curve (list of floats), signals (list of dicts with date+action+price), generated_at

#### `generator.py`
- Function `generate_strategy(prompt: str) -> StrategyConfig`
- Calls Claude API (`claude-opus-4-5`) with a system prompt that instructs it to output a valid `StrategyConfig` JSON
- System prompt must instruct Claude to: define clear entry/exit rules, specify all numeric parameters with defaults, output valid JSON only
- Parse and validate the response as `StrategyConfig`
- Raise `ValueError` with clear message if Claude returns invalid JSON

#### `evaluator.py`
- Function `evaluate_strategy(config: StrategyConfig, symbol: str, period: str, initial_capital: float) -> EvalResult`
- Fetch OHLCV data via yfinance (`yf.download(symbol, period=period, interval="1d", auto_adjust=True)`)
- Implement a vectorized backtest engine:
  - Apply strategy filters and signal logic to generate buy/sell signals
  - Simulate trades: enter on next open after signal, exit on next signal or end of period
  - No fractional shares, no leverage, no shorting in v1
  - Track equity curve daily
- Compute metrics:
  - `total_return_pct` = (final_equity - initial_capital) / initial_capital * 100
  - `sharpe_ratio` = annualized return / annualized volatility (252 trading days, risk-free rate = 0.04)
  - `max_drawdown_pct` = max peak-to-trough decline on equity curve
  - `win_rate` = profitable trades / total trades * 100
  - `total_trades` = count of completed round trips

#### `router.py`
Mount at `/strategies` prefix. Endpoints:
- `POST /strategies/generate` — body: `GenerateRequest`, returns `StrategyConfig`
- `POST /strategies/evaluate` — body: `EvalRequest`, returns `EvalResult`
- `GET /strategies/` — returns list of saved strategies from DB (table: `strategies`)
- `POST /strategies/save` — saves a `StrategyConfig` to DB, returns saved record with id

Import the router in `backend/app/main.py`.

#### DB Migration
Create table SQL (run on startup via `asyncpg` in `main.py`):
```sql
CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    config_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluations (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id),
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    metrics_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

### 2. Frontend — `frontend/src/app/strategies/`

#### `page.tsx`
Full strategies page with two sections:

**Section A — Generator:**
- Large textarea: "Describe your strategy in plain English..."
- Generate button (electric yellow `#e8ff47`, black text)
- Loading state: spinning dot animation, text "Claude is thinking..."
- On success: display generated `StrategyConfig` as a readable card (name, description, type badge, parameters table)
- Error state: red border, error message

**Section B — Evaluator:**
- Only shown after a strategy is generated
- Symbol input (default: AAPL), Period selector (3m / 6m / 1y / 2y), Capital input (default: $10,000)
- Run Backtest button
- Results panel:
  - 4 metric cards: Total Return, Sharpe Ratio, Max Drawdown, Win Rate
  - Equity curve chart (use `recharts` LineChart — already likely in deps, else add it)
  - Trade log table: date, action (BUY/SELL), price, P&L

**Styling:**
- All on `#0a0a0a` background
- Monospace font for all numbers and data
- Yellow accent for active states and positive returns
- Red for negative returns and losses

---

## Requirements Checklist

Before considering this complete, verify:

- [ ] All 4 backend endpoints return correct HTTP status codes (200, 422 for validation errors, 500 for upstream failures)
- [ ] `generate_strategy` handles Claude API errors gracefully (timeout, invalid JSON)
- [ ] Backtest engine handles edge cases: no signals generated, single trade, 100% loss
- [ ] DB tables created on backend startup (idempotent)
- [ ] Frontend shows loading and error states for both generate and evaluate flows
- [ ] Equity curve renders correctly for flat, up, and down scenarios
- [ ] CORS not broken — frontend can reach backend endpoints
- [ ] All new Python deps added to `backend/requirements.txt` (`anthropic`, `yfinance`, `pandas`, `numpy`)
- [ ] Docker rebuild instructions tested: `docker compose build backend && docker compose up -d backend`

---

## What NOT to Do

- Do not use an ORM (SQLAlchemy etc.) — raw asyncpg only
- Do not add authentication yet
- Do not support shorting or leverage in the backtest
- Do not use any charting library other than recharts on the frontend
- Do not deviate from the design system (colors, fonts defined above)
