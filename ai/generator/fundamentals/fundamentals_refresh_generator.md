# Generator — fundamentals refresh layer (lazy TTL + earnings-aware ingest)

**Module:** `fundamentals` (additive — first prompt pair stays locked)

## Purpose
Keep stored statements fresh without wasteful daily refetches. Two layers:
1. **Lazy TTL (read path)** — stale-while-revalidate: cold reads fetch+wait; warm
   stale reads serve immediately + refresh in the background. Surface `as_of`.
2. **Earnings-aware ingest (write path)** — refresh a tracked ticker only around
   its earnings (Finnhub calendar), polling until its new quarter appears.

## Decisions (fixed)
- Statements from yfinance (`ingest_statements`); earnings dates from Finnhub
  `/calendar/earnings` (free). Reuse the lifespan task pattern (Finnhub ws).
- **Market-day math uses the real NYSE calendar** (`exchange_calendars`, `XNYS`),
  NOT weekday approximation — wrapped in `market_calendar.py`.
- Done signal: `MAX(period_end) ≥ expected_period_end` (new quarter actually
  appeared) — not merely "fetched".
- Age-out: **T+2 trading days** (NYSE calendar). Poll every 30 min in a daily
  window (06:00–22:00 ET); idle when the watch queue is empty.
- Scheduler is in-process asyncio (no APScheduler); resumable via DB tables.

## Schema (append to DB_MIGRATIONS, idempotent)
- `earnings_calendar(symbol, earnings_date, hour, fiscal_quarter, fiscal_year,
  expected_period_end, source DEFAULT 'finnhub', fetched_at, UNIQUE(symbol,earnings_date))`.
- `earnings_watch(symbol, earnings_date, expected_period_end, status
  DEFAULT 'pending', attempts DEFAULT 0, last_polled_at, created_at, resolved_at,
  UNIQUE(symbol,earnings_date))`.

## Files to create (`backend/app/fundamentals/`)
- `market_calendar.py` — `is_trading_day(d)`, `add_trading_days(d, n)`,
  `trading_days_between(a, b)` over `exchange_calendars.get_calendar("XNYS")`.
  Module-level cached calendar instance.
- `calendar.py` — `async sync_earnings_calendar(conn, days_ahead=14)`: httpx GET
  `https://finnhub.io/api/v1/calendar/earnings?from=&to=` with header
  `X-Finnhub-Token`; for tracked equities upsert `earnings_calendar`;
  `expected_period_end` derived from (fiscal_quarter, fiscal_year) → quarter-end
  date. `async seed_watch(conn)`: insert pending `earnings_watch` for calendar
  rows with `earnings_date <= today` not already resolved.
- `refresh.py`:
  - `async poll_earnings_watch(pool) -> dict[str,int]`: per pending row →
    `ingest_statements` → if `MAX(period_end) ≥ expected_period_end` set
    status='done', resolved_at=NOW; elif `add_trading_days(earnings_date,2) <
    today` set status='aged_out' (log); else attempts+=1, last_polled_at=NOW.
  - `async ensure_fresh(pool, symbol, *, tracked) -> None`: read-path TTL. No
    rows → `ingest_statements` (block). `MAX(fetched_at)` older than TTL
    (tracked=30d, ad-hoc=7d) → return now + `asyncio.create_task` background
    refresh, guarded by a module-level per-symbol in-flight `set[str]`.
- `scheduler.py` — `FundamentalsScheduler(pool)`: asyncio loop; once/day
  `sync_earnings_calendar`+`seed_watch`; every `EARNINGS_POLL_MINUTES` inside the
  window run `poll_earnings_watch` only if pending rows exist. `run()`/`stop()`,
  backoff on error, CancelledError-safe.

## Modify
- `router.py` — `statements`/`metrics` call `ensure_fresh(pool, symbol,
  tracked=<is_tracked>)` before loading; add `as_of` (latest `fetched_at`) to
  `StatementsResponse`/`MetricsResponse` (+ `models.py`).
- `main.py` — append DDL; start/stop `FundamentalsScheduler` in lifespan; optional
  `/health` `earnings_watch_pending` count.
- `requirements.txt` — add `exchange-calendars>=4.5`.
- `.env.example` + `docker-compose.yml` — `FUNDAMENTALS_TTL_TRACKED_DAYS=30`,
  `FUNDAMENTALS_TTL_ADHOC_DAYS=7`, `EARNINGS_POLL_MINUTES=30`,
  `EARNINGS_AGEOUT_TRADING_DAYS=2`, `EARNINGS_POLL_WINDOW=06:00-22:00`.

## Constraints
- ruff + strict mypy + pytest green; full type annotations.
- Missing FINNHUB_API_KEY → scheduler skips calendar sync (logs), TTL still works.
- yfinance partial/empty → don't mark done; retry; bounded by T+2.
- Resumable across restart (state in `earnings_watch`).
