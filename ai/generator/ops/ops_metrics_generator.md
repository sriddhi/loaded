# Generator — `ops` module (observability / Tools tab)

**Module:** `ops` (`backend/app/ops/**`), mounts at `/ops`.

## Purpose
A lightweight, in-process observability layer that powers the **Tools** tab. It
surfaces, for the whole running app:
- **Jobs** — every background or UI-triggered unit of work (signal job,
  backtester, retention, fundamentals scheduler, finnhub ws, …): state, run/error
  counts, last run, latency (avg + p95), last error. Each job is tagged with a
  `source` of `backend` or `ui`.
- **API** — per-endpoint traffic: calls, error count + rate, latency (avg + p95),
  last status code.
- **Insights** — signal row counts per symbol + overall backtest hit-rate per
  horizon.

**This is a read-only monitoring surface. It never executes trades, never mutates
domain data, and is JWT-protected like every other module.**

## Decisions (fixed)
- In-memory singleton `METRICS` (resets on restart) — a live view, not a
  historical store. No new datastore/dependency.
- Thread-safe (a `threading.Lock`) because durations may be recorded from worker
  threads (e.g. yfinance via `asyncio.to_thread`).
- Bounded memory: per-job/endpoint latency samples kept in a `deque(maxlen=…)`.
- Jobs instrument themselves via a `track_job(name, source)` context manager that
  times the work and records success/failure (re-raising on error).
- API traffic captured by one `@app.middleware("http")` that records
  method, route template, status, and duration for **every** request (including
  4xx/5xx, so error metrics are real).

## `metrics.py`
- `JobStat` / `ApiStat` dataclasses with an `as_dict()` that derives
  `error_rate`, `avg_ms`, `p95_ms`.
- `Metrics`: `register_job`, `set_job_state`, `record_job`, `record_api`,
  `snapshot()` (sorted jobs + api + api_totals + uptime).
- Module singleton `METRICS`; `track_job` context manager.

## `router.py`
- `GET /ops/overview` → `METRICS.snapshot()` augmented with `insights`
  (per-symbol counts + per-horizon hit-rate queried from `spy_signals`).

## Wiring (`main.py`, exempt)
- Start/stop the jobs; `METRICS.register_job(...)` for each at startup.
- Add the API-metrics HTTP middleware. Mount `ops_router` under the JWT dep.

## Tests
- `test_ops_metrics.py`: record_job updates runs/errors/state/last_error;
  error_rate + p95 math; record_api increments calls + errors on ≥400;
  `track_job` records success and re-raises + records on failure.
- `test_ops_router.py`: `/ops/overview` returns jobs + api + insights with a
  mocked pool.
