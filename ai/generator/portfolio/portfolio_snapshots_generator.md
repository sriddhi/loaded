# Generator — `portfolio` module, snapshots scheduler + performance API

Daily EOD portfolio valuation history + performance analytics on top of the P1
core (see portfolio_core_generator.md — tables already exist).

## snapshots.py — PortfolioSnapshotScheduler

- Same shell as MacroScheduler: (pool, check_interval_seconds=600), stop(),
  run() with stop-aware sleep, catch-all per tick, CancelledError re-raised,
  `track_job("portfolio_snapshots", "backend")`.
- Tick gate: ET weekday, after 16:15 ET, and not already snapshotted today
  (any active portfolio missing today's row). Prefer today's `market_bars '1d'`
  close for valuation (screener job persists those); per-symbol fallback chain:
  1d bar close → resolve_price → last snapshot's detail price → avg cost.
  Gate on SPY's 1d bar for today existing, with a deadline (>=18:00 ET run
  anyway) so a failed screener never deadlocks snapshots.
- `async snapshot_portfolio(conn_or_pool, portfolio_row, price_for) -> row`:
  value holdings, compute net_flow_cents = Σ amount_cents of that day's
  deposit/withdrawal txs, cumulative realized from holdings, unrealized vs
  basis, upsert ON CONFLICT (portfolio_id, snapshot_date) DO UPDATE; detail
  JSONB = {symbol: {qty, price, value}} with the price source flagged when
  carried forward.
- Missed days: no backfill fabrication — history simply has gaps; TWR chaining
  skips gaps naturally (consecutive available rows).

## Performance + history API (added to portfolio/router.py)

- GET `/portfolio/{pid}/performance?range=1m|3m|6m|1y|all` →
  {series: [{date, total_value, twr_index}], twr_pct, simple_return_pct,
  realized_pnl, unrealized_pnl, income, net_contributions, beta, beta_coverage,
  disclaimer}.
  - series from portfolio_snapshots in range (ascending); twr_index = cumulative
    Π(1+r_t) starting 1.0 (uses math.chained_twr per-step logic).
  - twr_pct = chained TWR over the range; simple_return_pct =
    (current_total − net_contributions) / net_contributions where
    net_contributions = Σ deposits − Σ withdrawals (all-time, labeled
    "vs money in"); income = Σ dividend amounts in range.
  - beta: per-holding 1y daily returns from market_bars '1d' (fallback
    app.fundamentals.outlook.daily_closes), ≥60 aligned obs with SPY else
    excluded; portfolio beta = Σ wᵢβᵢ over covered weight; beta_coverage =
    covered weight fraction; beta null when coverage < .5.
- main.py: scheduler wiring + METRICS registration, mirroring macro block.

## Tests

test_portfolio_snapshots.py: close-source fallback chain; net_flow only counts
deposit/withdrawal; once-per-day gate; upsert idempotent (re-run same day
updates, no dup); TWR series math vs hand-computed fixture incl. a deposit day;
beta None under 60 obs. Performance endpoint shape test in
test_portfolio_router.py additions.

## Conventions

Cents in DB; ruff + strict mypy; Python 3.11-safe; scheduler never crashes.
