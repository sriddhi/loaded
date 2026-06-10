# Evaluator — fundamentals refresh layer

Checklist for lazy TTL + earnings-aware ingest. ✅/❌. Pass ≥ 9.5/10 (≥ 34/36).

## Market calendar (4)
- [ ] C1. `market_calendar.py` uses the real NYSE calendar (exchange_calendars XNYS).
- [ ] C2. `add_trading_days` skips weekends AND market holidays (tested across a holiday).
- [ ] C3. `is_trading_day` false on a known holiday (e.g. Jul 4), true on a normal weekday.
- [ ] C4. Calendar instance cached at module level (not rebuilt per call).

## Lazy TTL read path (7)
- [ ] T1. Cold (no rows) → `ingest_statements` blocks then serves.
- [ ] T2. Fresh (within TTL) → no refetch.
- [ ] T3. Stale (older than TTL) → serve immediately + background `asyncio.create_task` refresh.
- [ ] T4. TTL differs by tier (tracked 30d, ad-hoc 7d), env-configurable.
- [ ] T5. Per-symbol in-flight guard prevents duplicate concurrent refreshes.
- [ ] T6. `statements`/`metrics` responses include `as_of` (latest fetched_at).
- [ ] T7. Background-refresh failure does not break the served (stale) response.

## Earnings calendar sync (5)
- [ ] E1. Finnhub `/calendar/earnings` pulled via httpx with `X-Finnhub-Token`.
- [ ] E2. Only tracked equities upserted into `earnings_calendar`; idempotent.
- [ ] E3. `expected_period_end` derived from (fiscal_quarter, fiscal_year).
- [ ] E4. `seed_watch` inserts pending rows for earnings_date <= today, no dups.
- [ ] E5. Missing FINNHUB_API_KEY → sync skipped + logged (no crash).

## Poller (8)
- [ ] P1. Per pending row calls `ingest_statements`.
- [ ] P2. Marks **done** only when `MAX(period_end) ≥ expected_period_end`.
- [ ] P3. A same-day-late statement (period_end still old) stays pending, retries.
- [ ] P4. Ages out at **T+2 trading days** (NYSE calendar), status='aged_out', logged.
- [ ] P5. attempts/last_polled_at updated on each non-terminal poll.
- [ ] P6. Resumable: pending rows persist; restart re-reads them.
- [ ] P7. yfinance error/partial → not marked done; retried.
- [ ] P8. Returns counts (done/aged_out/pending) for observability.

## Scheduler + wiring (7)
- [ ] S1. In-process asyncio loop started/stopped in lifespan (no APScheduler).
- [ ] S2. Calendar sync + seed run once/day.
- [ ] S3. Poll every EARNINGS_POLL_MINUTES within EARNINGS_POLL_WINDOW only.
- [ ] S4. Idle (no work) when the watch queue is empty — not wasteful.
- [ ] S5. CancelledError-safe; backoff on error.
- [ ] S6. DDL + env vars added; `exchange-calendars` in requirements.
- [ ] S7. /health exposes pending-watch count (optional but present).

## Quality (5)
- [ ] Q1. ruff clean. Q2. strict mypy clean. Q3. pytest green.
- [ ] Q4. Coexists with the first fundamentals prompt pair (still locked).
- [ ] Q5. Benchmark result saved.
