# Evaluator — `macro` module (FRED trackers & SVM alerts)

Score each ❌/✅. All ❌ fixed before done.

## Data + freshness
- [ ] Works with no FRED key (CSV fallback) and uses the official API when
      `FRED_API_KEY` is set; bad/missing values (".") skipped safely.
- [ ] Observations upserted idempotently; history ≥ 1990; incremental refresh.
- [ ] Scheduler refreshes by frequency TTL (daily 6h / weekly 12h / monthly 24h),
      registered in METRICS, never crashes the loop; manual POST /macro/refresh.

## Signals (each unit-tested, fired + not-fired)
- [ ] real_wages_negative, margin_squeeze, policy_mistake, cpi_up_2y_down,
      two_year_below_3_5, ppi_hot_core_rolling, claims_4wk_above_250k,
      claims_spike_15pct, continuing_claims_rising_4w / 12m_high,
      ecb_hike_market_rejects, income_spread_falling_3m.
- [ ] Technical alerts (SPY 21dma, IGV/SMH 50dma) via existing close fetcher.
- [ ] Deterministic; missing data → alert skipped (not fired), never a crash.

## API / UI / safety
- [ ] /macro/trackers, /macro/alerts, /macro/series/{code}, /macro/refresh all
      JWT'd; 404/422 paths sane.
- [ ] /macro page renders cards + charts + alert badges + freshness; nav link;
      "not financial advice" label; design-system components.
- [ ] Read-only module (no orders); strict mypy + ruff clean; tests per file.
