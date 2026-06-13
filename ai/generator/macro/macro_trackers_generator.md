# Generator — `macro` module (FRED trackers & SVM alert playbook)

**Module:** `macro` (`backend/app/macro/**`), mounts at `/macro` (JWT).

## Purpose
Implement the Steven Van Metre chart-tracker playbook: ingest the FRED series
behind charts 1–8, keep them **automatically up to date as FRED updates**, compute
the derived signals (YoY, wage-income, spreads), evaluate the four alert patterns
(threshold / crossover-divergence / calendar / technical), and serve trackers +
alerts to a Macro UI page. Read-only macro analytics — not advice, no trading.

## Data source (fred.py)
- Official FRED API when `FRED_API_KEY` is set (`/fred/series` meta +
  `/fred/series/observations`); otherwise fall back to the keyless
  `fred.stlouisfed.org/graph/fredgraph.csv?id=` endpoint — the module must work
  without a key and upgrade automatically when one appears.
- Registry of series (registry.py): CPIAUCSL, DFF, FEDFUNDS, AWHNONAG, AHETPI,
  DGS2, DGS10, PPIFIS, WPSFD4131, ICSA, CCSA, PAYEMS, ECBDFR, IRLTLT01DEM156N,
  DEXUSEU — each with title, frequency (d/w/m), category.

## Freshness ("stay up to date as FRED updates")
- Postgres: `macro_series(code, title, frequency, fetched_at, fred_updated_at)` +
  `macro_observations(code, date, value)` upserts; history from 1990.
- `MacroScheduler` (lifespan job, mirrors RetentionJob; `track_job` METRICS):
  hourly tick refreshes any series whose TTL elapsed — daily series 6h TTL,
  weekly 12h, monthly 24h. Incremental fetch; never raises out of the loop.
- `POST /macro/refresh` forces a full refresh on demand.

## Trackers (registry-driven, charts 1–8)
cpi_vs_fedfunds, cpi_vs_wage_income (AWHNONAG×AHETPI YoY), cpi_vs_2y,
ppi_headline_vs_core, cpi_ppi_spread, initial_claims, continuing_claims,
ecb_and_bunds — each: series set, derived lines, last value(s), linked alerts.

## Alerts (signals.py — deterministic, unit-tested)
1. policy_mistake: CPI YoY falling (3m) while DFF flat/rising.
2. real_wages_negative: CPI YoY > income YoY.
3. income_spread_falling_3m: (income−CPI) YoY spread down 3 consecutive months.
4. cpi_up_2y_down: CPI YoY rising while DGS2 fell over ~20 trading days.
5. two_year_below_3_5: DGS2 < 3.5.
6. ppi_hot_core_rolling: headline−core PPI YoY > 1.5pts and core falling.
7. margin_squeeze: CPI YoY − PPI YoY < 0.
8. claims_4wk_above_250k; claims_spike_15pct (week > 15% above 4-wk avg).
9. continuing_claims_rising_4w; continuing_claims_12m_high.
10. ecb_hike_market_rejects: ECBDFR up while DE10Y fell over the same month.
Technical (pattern 4, via existing yfinance closes): spy_below_21dma,
igv_above_50dma, smh_above_50dma. Each alert returns
{id, name, pattern, fired, value, detail, series}.

## API (router.py)
GET /macro/trackers (cards: series points ≤ N + alerts), GET /macro/alerts,
GET /macro/series/{code}, POST /macro/refresh. All JWT (router-level mount).

## UI
`/macro` page (design system): fired-alerts strip, tracker cards with
multi-series LineChartView + alert badges + freshness; nav link. "Not financial
advice" label.

## Tests
Per-file: fred parse (API+CSV), registry sanity, refresh TTL/upsert logic with
mocked fetch, every alert rule on synthetic series (fired and not-fired paths),
router with mocked pool.
