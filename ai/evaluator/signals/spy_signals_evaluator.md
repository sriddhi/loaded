# Evaluator — `signals` module (SPY heuristic signal job)

✅/❌. Pass ≥ 9.5/10 (≥ 30/32).

## Engine (10)
- [ ] E1. `classify` is pure + deterministic (no I/O, no clock).
- [ ] E2. Horizons 5/10/20 supported via `compute_all`.
- [ ] E3. Strong up momentum series → `bullish`.
- [ ] E4. Strong down momentum series → `bearish`.
- [ ] E5. Recent-high-then-reversal-down series → `bull_trap`.
- [ ] E6. Recent-low-then-reversal-up series → `bear_trap`.
- [ ] E7. Flat series → `neutral`.
- [ ] E8. Insufficient data (too few samples) → `neutral`, no crash.
- [ ] E9. Confidence ∈ [0,1].
- [ ] E10. Thresholds scale with horizon (longer horizon needs a bigger move).

## Job + storage (8)
- [ ] J1. `fetch_spy_quote` parses Finnhub `/quote` `c`; returns None on error/0.
- [ ] J2. `tick_once` skips (returns None) when price unavailable.
- [ ] J3. `tick_once` loads recent prices from DB, appends, computes, inserts a row.
- [ ] J4. Inserted row has price + all three horizon labels + confidences.
- [ ] J5. `SpySignalJob.run` loops on the interval; `stop()` is responsive; CancelledError-safe.
- [ ] J6. `signals_enabled()` False without FINNHUB_API_KEY; job not started then.
- [ ] J7. Buffer seeded from DB on startup (restart-safe) — recent prices reused.
- [ ] J8. Errors in a tick don't kill the loop (logged, continue).

## API + wiring (8)
- [ ] A1. `/signals/*` JWT-protected.
- [ ] A2. `GET /spy/latest` returns the newest row (404 if none).
- [ ] A3. `GET /spy/history?limit=` returns recent rows, newest first.
- [ ] A4. `POST /spy/run` computes + stores + returns one signal.
- [ ] A5. DDL `spy_signals` + ts index added; idempotent.
- [ ] A6. Job started/stopped in lifespan; SIGNAL_INTERVAL_SECONDS configurable.
- [ ] A7. mandate.json gates the module; prompts locked.
- [ ] A8. No trade execution anywhere in the module.

## UI + quality (6)
- [ ] U1. /signals page shows SPY price + 5/10/20m labels (color-coded) + history.
- [ ] U2. Auto-refresh + a manual "Run now" button.
- [ ] U3. Visible "heuristic indicator, not advice/prediction" disclaimer.
- [ ] U4. ruff clean. U5. strict mypy clean. U6. pytest + eslint + tsc green.
