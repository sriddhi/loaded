# Strategy Evaluator Prompt

**Feature:** Strategy Generator + Evaluator  
**Version:** 1.0  
**Checks against:** `ai/generator/strategies/strategy_generator.md`

---

## Context

You are a senior engineer reviewing the Strategy Generator + Evaluator feature for **Loaded**. Your job is to verify that the implementation meets every requirement in the generator spec. Be precise — report pass/fail for each check with evidence (file path, line number, or specific issue).

---

## How to Run This Evaluation

1. Read `ai/generator/strategies/strategy_generator.md` fully
2. Read all files in `backend/app/strategies/` and `frontend/src/app/strategies/`
3. Read `backend/app/main.py` to verify router import and DB migration
4. Read `backend/requirements.txt` to verify dependencies
5. Run each check below and mark ✅ PASS or ❌ FAIL with evidence

---

## Checks

### Backend — Models (`backend/app/strategies/models.py`)

- [ ] `StrategyConfig` exists with fields: name, description, type (enum), parameters (dict), filters (dict), signal_logic
- [ ] `StrategyType` enum has: MOMENTUM, BREAKOUT, MEAN_REVERSION, CUSTOM
- [ ] `GenerateRequest` has `natural_language_prompt` (str) and optional `context`
- [ ] `EvalRequest` has: strategy_config, symbol, period (default "1y"), initial_capital (default 10000.0)
- [ ] `EvalResult` has all metric fields: total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate, total_trades, equity_curve, signals, generated_at

### Backend — Generator (`backend/app/strategies/generator.py`)

- [ ] Uses Claude API model `claude-opus-4-5`
- [ ] Has a system prompt that instructs Claude to output valid JSON only
- [ ] System prompt specifies: clear entry/exit rules, numeric parameters with defaults
- [ ] Parses Claude response and validates as `StrategyConfig`
- [ ] Raises `ValueError` with meaningful message if JSON is invalid or unparseable
- [ ] Handles Claude API timeout or connection error without crashing

### Backend — Evaluator (`backend/app/strategies/evaluator.py`)

- [ ] Fetches OHLCV via yfinance with `auto_adjust=True`
- [ ] Backtest is vectorized (uses pandas operations, not row-by-row Python loops)
- [ ] Entry: next open after signal bar (not same-bar fill)
- [ ] No shorting, no leverage, no fractional shares
- [ ] Equity curve is tracked daily (same length as OHLCV dataframe)
- [ ] `total_return_pct` formula: `(final - initial) / initial * 100`
- [ ] `sharpe_ratio` uses 252-day annualization and 4% risk-free rate
- [ ] `max_drawdown_pct` is peak-to-trough on equity curve (not price)
- [ ] `win_rate` is based on completed round trips only
- [ ] Edge case handled: no signals → returns zero trades, flat equity curve, 0% return
- [ ] Edge case handled: single trade → no division by zero in win_rate or sharpe

### Backend — Router (`backend/app/strategies/router.py`)

- [ ] Router prefix is `/strategies`
- [ ] `POST /strategies/generate` returns `StrategyConfig` with HTTP 200
- [ ] `POST /strategies/evaluate` returns `EvalResult` with HTTP 200
- [ ] `GET /strategies/` returns list from DB `strategies` table
- [ ] `POST /strategies/save` inserts into DB and returns saved record with id
- [ ] Validation errors return HTTP 422 (Pydantic does this automatically — verify not suppressed)
- [ ] Upstream failures (Claude timeout, yfinance error) return HTTP 500 with error detail

### Backend — Integration (`backend/app/main.py`)

- [ ] Strategy router imported and included: `app.include_router(strategies_router)`
- [ ] DB migration SQL runs on startup (in `@app.on_event("startup")` or lifespan)
- [ ] Migration is idempotent (`CREATE TABLE IF NOT EXISTS`)
- [ ] Both `strategies` and `evaluations` tables created

### Backend — Dependencies (`backend/requirements.txt`)

- [ ] `anthropic` is listed (version pinned or `>=`)
- [ ] `yfinance` is listed
- [ ] `pandas` is listed
- [ ] `numpy` is listed

### Frontend — Page (`frontend/src/app/strategies/page.tsx`)

- [ ] Page exists at correct App Router path
- [ ] Generator section has textarea and Generate button
- [ ] Button color is `#e8ff47` with black text
- [ ] Loading state shown during API call (spinner or animation + "Claude is thinking...")
- [ ] Strategy card shown on success (name, description, type, parameters table)
- [ ] Error state shown on failure (red border + message)
- [ ] Evaluator section only rendered after strategy is generated
- [ ] Symbol input, period selector (3m/6m/1y/2y), capital input present
- [ ] Run Backtest button present
- [ ] 4 metric cards rendered: Total Return, Sharpe Ratio, Max Drawdown, Win Rate
- [ ] Positive returns shown in yellow `#e8ff47`, negative in red
- [ ] Equity curve chart rendered using recharts LineChart
- [ ] Trade log table shows: date, action, price, P&L
- [ ] Background is `#0a0a0a`, text is `#f5f5f5`
- [ ] All numbers use monospace font

### End-to-End Checks

- [ ] `POST /strategies/generate` with prompt "momentum breakout on high volume" returns valid StrategyConfig
- [ ] `POST /strategies/evaluate` with that config + symbol AAPL + period 1y returns EvalResult with no null metric fields
- [ ] Frontend generate flow completes without console errors
- [ ] Frontend backtest flow renders equity curve without blank chart
- [ ] Docker rebuild succeeds: `docker compose build && docker compose up -d`
- [ ] `/health` endpoint still returns 200 after changes (nothing broken)

---

## Scoring

After all checks, compute:

```
completeness  = (backend checks passed) / (total backend checks) * 10
ui_coverage   = (frontend checks passed) / (total frontend checks) * 10
e2e_coverage  = (e2e checks passed) / (total e2e checks) * 10
overall       = (completeness + ui_coverage + e2e_coverage) / 3
```

Report the score and list all ❌ FAIL items with specific fix instructions.

---

## Output Format

```
## Evaluation Report — Strategy Generator + Evaluator
**Date:** {date}
**Overall Score:** {score}/10

### ✅ Passing ({n})
- list

### ❌ Failing ({n})
- Check: {check name}
  File: {path}
  Issue: {what's wrong}
  Fix: {specific instruction}

### Score Breakdown
| Area | Score |
|------|-------|
| Backend completeness | x/10 |
| Frontend coverage | x/10 |
| End-to-end | x/10 |
| **Overall** | **x/10** |
```
