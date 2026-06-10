# Generator — `strategies` backtest-run framework

**Module:** `strategies` (`backend/app/strategies/**`).

## Purpose
Run a saved strategy's backtest on demand or on a schedule, across one or more
timeframes, and persist each result to `strategy_runs` for history + the
per-strategy observability view.

## Decisions (fixed)
- Reuse the existing vectorized engine `evaluator.evaluate_strategy` (pandas /
  yfinance, next-open fill, no shorting/leverage). Do not reimplement.
- A backtest may run for multiple periods (e.g. `["1y","6mo","3mo"]`).

## `backtest.py`
- `async def run_backtest_for(pool, strategy, period, symbol, source) -> dict`:
  run `evaluate_strategy`, store an `EvalResult` into `strategy_runs`
  (`run_type='backtest'`, metrics_json + equity_curve_json, duration_ms, source),
  return the result + run id. Errors → a `status='error'` run row, not a crash.
- Endpoint `POST /strategies/{id}/backtest` (on-demand, source=`ui`) loops the
  requested periods; `GET /strategies/{id}/runs` lists history.

## Tests
- `run_backtest_for` persists a run row with metrics; multi-period loop; error
  path records a failed run.
