# Evaluator — `ops` module (observability / Tools tab)

Score each ❌/✅. All ❌ must be fixed before the feature is done.

## Correctness
- [ ] `record_job` increments `runs`, sets `last_run`/`last_duration_ms`, appends
      latency; on `ok=False` increments `errors`, stores `last_error`, sets state
      `error`.
- [ ] `error_rate` = errors/runs (0 when no runs); `avg_ms` and `p95_ms` derive
      from the latency samples; empty → `None`.
- [ ] `record_api` increments `calls`, sets `last_status`, and increments
      `errors` only when `status >= 400`.
- [ ] `track_job` records on both success and failure, and **re-raises** on
      failure (does not swallow exceptions).
- [ ] `snapshot()` returns `jobs`, `api`, `api_totals` (calls/errors/error_rate),
      and `uptime_seconds`.
- [ ] `GET /ops/overview` returns the snapshot plus `insights.per_symbol` and
      `insights.hit_rate` (per horizon, with hits/total/pending/accuracy).

## Safety / guardrails
- [ ] Read-only: no trade execution, no domain mutation anywhere in the module.
- [ ] `/ops/*` is mounted under the JWT auth dependency.
- [ ] Memory is bounded (deque maxlen) — no unbounded growth.
- [ ] Thread-safe access (lock) around shared dict mutation.

## Tests
- [ ] Unit tests cover record_job (success + error), error_rate/p95, record_api
      thresholds, and `track_job` re-raise.
- [ ] Router test asserts `/ops/overview` shape with a mocked pool.

## Quality
- [ ] No new external dependency or datastore.
- [ ] Strict mypy + ruff clean.
