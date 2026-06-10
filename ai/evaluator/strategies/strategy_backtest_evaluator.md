# Evaluator — `strategies` backtest-run framework

Score each ❌/✅. Fix all ❌ before done.

## Correctness
- [ ] `run_backtest_for` reuses `evaluate_strategy` (no reimplementation) and
      persists one `strategy_runs` row with metrics_json + equity_curve_json +
      duration_ms + source.
- [ ] Supports multiple periods (loops); each period → its own run row.
- [ ] Errors record a `status='error'` run row rather than crashing.
- [ ] `POST /strategies/{id}/backtest` (on-demand) + `GET /strategies/{id}/runs`
      (history) work and are JWT-protected.

## Tests / quality
- [ ] Persist-a-run, multi-period, and error-path covered.
- [ ] Strict mypy + ruff clean.
