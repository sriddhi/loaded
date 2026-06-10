# Generator — `strategies` runtime (saved strategies, modes, scheduler)

**Module:** `strategies` (`backend/app/strategies/**`).

## Purpose
Saved-strategy lifecycle + execution. Each strategy has a **mode** set per
strategy: `backtest` (backtest only), `signal` (compute today's signal), or
`paper` (place PAPER orders + keep validating). A scheduler runs due strategies;
every run is logged to `strategy_runs` and observable via ops `METRICS`.

**SAFETY (hard): no real trades. `paper` mode places orders ONLY on the Alpaca
paper account, behind a guard that refuses unless paper trading is configured.
Strategies are disabled by default; scheduling is opt-in per strategy.**

## Schema (in `main.py` DB_MIGRATIONS, idempotent)
- `strategies` += `enabled BOOLEAN DEFAULT false`, `mode TEXT DEFAULT 'backtest'`,
  `symbols TEXT[]`, `run_config_json JSONB DEFAULT '{}'`, `updated_at TIMESTAMPTZ`.
- `strategy_runs(id, strategy_id, run_type, status, source, period, metrics_json,
  equity_curve_json, detail, duration_ms, created_at)`.

## `runtime.py`
- `latest_signal(config, symbol) -> "BUY"|"SELL"|"HOLD"` — reuse
  `evaluator._generate_signals` on recent bars; read the last bar.
- `place_paper_order(symbol, side, qty)` — **paper-gated**: assert paper config
  (`ALPACA_PAPER_TRADE` truthy / paper base url) or skip + log; never live.
- `run_strategy_once(pool, strategy)` — branch on mode; write a `strategy_runs`
  row; wrap in `track_job("strategy_scheduler"/run, source)`.
- `StrategyScheduler` — in-process asyncio loop (mirror `RetentionJob`): each
  minute load enabled strategies, run those whose `run_config.schedule` is due
  (`manual|interval|daily` ET). Graceful start/stop; `METRICS.register_job`.

## Tests
- `latest_signal` from a synthetic series; scheduler due-logic; **paper gate
  refuses when not paper-configured**; `run_strategy_once` writes a run per mode.
