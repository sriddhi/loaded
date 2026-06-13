# Evaluator — `portfolio` snapshots scheduler + performance API

Score each ❌/✅. All ❌ fixed before done.

- [ ] Snapshot valuation prefers today's 1d bar; fallback chain (resolve_price →
      last snapshot detail → avg cost) unit-tested; carried-forward prices
      flagged in detail.
- [ ] net_flow_cents counts ONLY that day's deposits/withdrawals (signed);
      dividends count as income, not flow.
- [ ] Upsert idempotent — same-day re-run updates the row, never duplicates.
- [ ] Scheduler gates: weekday + after-close + missing-today check + SPY-bar
      gate with deadline override; loop survives exceptions; METRICS-registered;
      clean shutdown.
- [ ] TWR: per-step r_t = (V_t − F_t − V_{t−1})/V_{t−1}; cumulative index
      matches hand fixture; a large deposit on a flat day yields ~0 TWR.
- [ ] simple_return labeled "vs money in"; income aggregates dividends;
      net_contributions = deposits − withdrawals.
- [ ] Beta: ≥60 aligned daily returns vs SPY required per symbol; portfolio
      beta weight-aggregated; null under 50% coverage; never crashes on missing
      bars.
- [ ] Performance endpoint owner-scoped (404), range param respected,
      disclaimer present; UI performance chart renders from the series.
- [ ] ruff + strict mypy clean; tests per file.
