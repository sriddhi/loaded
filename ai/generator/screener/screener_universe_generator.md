# Generator — `screener` module, universe + data pipeline + nightly job

Build the DISCOVER data layer: a ~550-symbol universe (S&P 500 + Nasdaq-100),
batched daily-close ingestion, statement-freshness management, and the nightly
scheduler that feeds the scoring engine (see screener_scoring_generator.md).

## Module layout

```
backend/app/screener/
  __init__.py
  universe.py   static seed constants + refresh/upsert into equities + universe_members
  data.py       batched yf.download closes → market_bars '1d'; staleness scan
  job.py        ScreenerScheduler (nightly after ET close) + run orchestration
  models.py     Pydantic response models (shared with scoring/router)
  scoring.py    (spec'd separately)
  router.py     (spec'd separately)
```

## Schema (DB_MIGRATIONS)

- `universe_members(equity_id INT REFERENCES equities(id), universe TEXT
  'sp500'|'ndx100', is_current BOOLEAN DEFAULT TRUE, first_seen DATE, last_seen
  DATE, PRIMARY KEY(equity_id, universe))`.
- `screener_scores` (defined in the scoring generator; created in the same
  migration block).

## universe.py

- `UNIVERSE_SEED: list[tuple[str, str, str, str]]` — (symbol, name, gics_sector,
  universe) for current S&P 500 + Nasdaq-100 members; symbols in both lists get
  two rows. Seed is generated from public constituent lists at build time and is
  refreshable via the admin endpoint later; accuracy drift (~20 names/yr) is
  acceptable and self-corrects on refresh.
- `async refresh_universe(pool) -> {"added": int, "marked_stale": int, "total": int}`:
  upsert each seed symbol into `equities` (INSERT ... ON CONFLICT (symbol) DO
  UPDATE SET name/gics_sector only when currently NULL — never clobber richer
  data from fundamentals ingestion), then upsert `universe_members`
  (is_current=TRUE, last_seen=today); members no longer in the seed →
  is_current=FALSE.
- `async universe_symbols(pool, universe: str | None) -> list[dict]` — current
  members with equity_id, symbol, name, sector.

## data.py

- `async refresh_closes(pool, symbols, *, lookback_days=10, chunk_size=50)`:
  batched `yf.download(" ".join(chunk), period=..., interval="1d",
  group_by="ticker", threads=False)` via asyncio.to_thread, ~11 calls for 550
  symbols; upsert rows into `market_bars(time, equity_id, timeframe='1d', open,
  high, low, close, volume)` with executemany ON CONFLICT DO UPDATE. First run
  (symbol has no 1d bars) uses lookback ~320 days. ALWAYS include SPY, IGV, SMH
  in the pull set (macro technicals + beta reuse). Per-chunk failures logged and
  skipped — never abort the night.
- `async stale_statement_symbols(pool, symbols, max_age_days=30) -> list[str]`:
  symbols whose newest financial_statements.fetched_at is older than the TTL (or
  absent), ordered stalest-first.
- `async closes_map(pool, symbols, days=320) -> dict[symbol, list[float]]` —
  ascending daily closes from market_bars '1d' for the scoring pass.

## job.py — ScreenerScheduler

- Constructor (pool, check_interval_seconds=600); `stop()`; `run()` loop with
  1-second stop-aware sleeps; never crashes (catch-all per tick, log + continue);
  CancelledError re-raised.
- Tick gate: ET weekday, after 16:10 ET, and no `screener_scores` row for today.
- `async run_screener(pool, *, ingest_budget=int(env SCREENER_INGEST_BUDGET, 120))`
  under `track_job("screener_nightly", "backend")` and a module-level
  asyncio.Lock (`SCREENER_LOCK`) shared with the manual endpoint — concurrent
  runs impossible (endpoint returns 409 when locked):
  1. refresh_universe
  2. ingest stale statements via existing `app.agents.ingest` helpers, capped at
     `ingest_budget`, Semaphore(2) + ~1.5s jittered sleep between calls
  3. refresh_closes for universe ∪ {SPY, IGV, SMH}
  4. scoring pass + upsert + rank update (scoring generator)
  Phases fault-isolated: a failed phase logs and the rest proceed (scoring runs
  on cached data).
- main.py: lifespan start + METRICS.register_job("screener_nightly", ...) +
  shutdown stop/cancel — mirror MacroScheduler wiring exactly.

## Conventions

Raw asyncpg; ruff+strict mypy (typed locals at cross-module imports); Python
3.11-safe; tests per app file (test_screener_{universe,data,job,models}.py);
yfinance only via to_thread; never raises out of the scheduler loop.
