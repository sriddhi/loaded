# Evaluator — `screener` universe + data pipeline + nightly job

Score each ❌/✅. All ❌ fixed before done.

- [ ] Seed contains current S&P 500 + Nasdaq-100 (~500-560 unique symbols);
      overlap symbols present under both universes; no duplicate (symbol,
      universe) pairs (unit-tested).
- [ ] refresh_universe upserts equities WITHOUT clobbering existing
      name/sector data; departed members flagged is_current=FALSE, never deleted.
- [ ] Closes ingestion is batched (≈ symbols/chunk_size yf.download calls, not
      per-symbol); first-run lookback ~320d vs incremental ~10d; SPY/IGV/SMH
      always included; per-chunk failure skips, never aborts (unit-tested with
      mocked yf).
- [ ] Statement staleness: only symbols past the 30-day TTL selected,
      stalest-first, budget cap honored (unit-tested).
- [ ] Scheduler: weekday + after-close + once-per-day gating; module-level lock
      makes nightly tick and manual run mutually exclusive; phases
      fault-isolated; loop survives any exception; registered in METRICS;
      clean stop on shutdown.
- [ ] All DB writes idempotent (ON CONFLICT); money/closes stored consistently
      with existing market_bars conventions.
- [ ] ruff + strict mypy clean (both hook and backend-cwd invocations); tests
      per app file; Python 3.11-compatible.
