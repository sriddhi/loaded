# Evaluator — `strategies` runtime

Score each ❌/✅. Fix all ❌ before done.

## Correctness
- [ ] `mode` ∈ `backtest|signal|paper`; strategies `enabled=false` by default.
- [ ] `latest_signal` reuses `_generate_signals` and returns BUY/SELL/HOLD.
- [ ] `run_strategy_once` branches on mode and writes exactly one `strategy_runs`
      row (status ok/error, source, duration_ms).
- [ ] `StrategyScheduler` only runs enabled strategies whose schedule is due;
      graceful start/stop; registered in METRICS.

## Safety (critical)
- [ ] `place_paper_order` refuses/skips when paper trading is not configured —
      verified by a test. Never places a live order.
- [ ] Scheduling is opt-in; disabled strategies never run.
- [ ] `/strategies/*` under JWT.

## Tests / quality
- [ ] Paper-gate refusal, scheduler due-logic, per-mode run row all covered.
- [ ] Strict mypy + ruff clean.
