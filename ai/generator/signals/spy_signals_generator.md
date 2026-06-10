# Generator — `signals` module (SPY heuristic signal job)

**Module:** `signals` (`backend/app/signals/**`), mounts at `/signals`.

## Purpose
A **test/indicator** job that runs every 1 minute and emits a directional signal
for SPY over the next **5 / 10 / 20 minutes**, labelled one of:
`bullish | bearish | bull_trap | bear_trap | neutral`. Plus an API + UI to view
the latest signal and recent history.

**This is a transparent heuristic over recent price action — NOT a market
prediction and NOT financial advice. No trade execution.**

## Decisions (fixed)
- Price source: Finnhub `/quote` (free; works after-hours, returns last price).
  Reuse `FINNHUB_API_KEY`. (No Alpaca dependency.)
- 1-minute cadence (`SIGNAL_INTERVAL_SECONDS`, default 60). In-process asyncio
  job in lifespan (mirrors the fundamentals scheduler / finnhub ws).
- Deterministic, pure `classify(prices, horizon)` engine so it is fully testable.
- Persist every tick; the buffer is seeded from the DB on startup (restart-safe).

## Signal engine — `engine.py`
- `HORIZONS = [5, 10, 20]`.
- `classify(prices: list[float], horizon_min: int) -> tuple[str, float]`
  over most-recent-last 1-min samples:
  - momentum `ret` over a horizon-scaled lookback window;
  - recent high/low + reversal from the extreme;
  - thresholds scale with √horizon (vol grows with time);
  - **bull_trap** = made a recent high then reversed down past a threshold
    (failed breakout); **bear_trap** = recent low then reversed up (failed
    breakdown); else momentum sign → bullish/bearish; flat/insufficient → neutral.
  - returns `(label, confidence∈[0,1])`.
- `compute_all(prices) -> dict[int, tuple[str, float]]` for all horizons.

## Job + storage — `job.py`
- `async fetch_spy_quote() -> float | None` (Finnhub /quote `c`; None on error/0).
- `async tick_once(pool) -> dict | None`: fetch price (None → skip), load recent
  prices from DB, append, `compute_all`, insert a `spy_signals` row, return it.
- `class SpySignalJob(pool)`: `run()` loop every interval calling `tick_once`;
  `stop()`; backoff + CancelledError-safe. `signals_enabled()` → False if no key.

## Schema (append to DB_MIGRATIONS, idempotent)
`spy_signals(id SERIAL PK, ts TIMESTAMPTZ DEFAULT NOW(), price NUMERIC(12,4),
sig_5m TEXT, conf_5m NUMERIC(4,3), sig_10m TEXT, conf_10m NUMERIC(4,3),
sig_20m TEXT, conf_20m NUMERIC(4,3))`; index on `ts DESC`.

## API — `router.py` (prefix `/signals`, JWT)
- `GET /signals/spy/latest` → most recent `SpySignal` (404 if none yet).
- `GET /signals/spy/history?limit=60` → recent rows.
- `POST /signals/spy/run` → force one tick now (compute + store), return it
  (manual trigger for testing/demo).

## Models — `models.py`
`HorizonSignal{horizon_min,label,confidence}`, `SpySignal{ts,price,signals[]}`,
`SpySignalHistory{signals[]}`.

## Wiring
- `main.py`: DDL; mount router with `_auth_dep`; start/stop `SpySignalJob` in
  lifespan if enabled; optional /health field.
- `.env.example` + `docker-compose.yml`: `SIGNAL_INTERVAL_SECONDS=60`.

## Constraints
- ruff + strict mypy + pytest green; full type annotations.
- Missing FINNHUB_API_KEY → job not started (logged); endpoints still serve stored history.
- After-hours: /quote returns a static last price → mostly `neutral` live (honest);
  the 4 directional labels are exercised by unit tests with synthetic series.
- UI must show a "heuristic indicator, not advice/prediction" disclaimer.
