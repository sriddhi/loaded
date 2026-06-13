# Generator — `screener` module, scoring engine + API (DISCOVER pillar)

Deterministic composite scoring over the universe, persisted per day, served
ranked with per-pillar breakdowns and human-readable reasons. Pure functions —
no I/O in scorers, missing data degrades to None (never raises). Educational
labels only — every response carries "not financial advice".

## Schema

`screener_scores(id SERIAL PK, equity_id INT REFERENCES equities(id), score_date
DATE, composite NUMERIC(5,1), value_score/quality_score/growth_score/
momentum_score/analyst_score/macro_fit_score NUMERIC(5,1) NULL, coverage
NUMERIC(4,3) NOT NULL, candidate TEXT NOT NULL, rank INTEGER, price_cents
BIGINT, reasons JSONB DEFAULT '[]', inputs JSONB DEFAULT '{}', created_at,
UNIQUE(equity_id, score_date))` + index (score_date, rank).

## scoring.py — pure

- `SymbolInputs` (TypedDict): symbol, sector, statements rows (annual, newest
  first, dicts), analyst row (target_price_mean, recommendation, num_analysts)
  | None, closes (ascending list[float]), price (float | None), fired_alert_ids
  (set[str]), sector_pe_median (float | None).
- `DEFAULT_WEIGHTS = {"value": .25, "quality": .20, "growth": .15, "momentum":
  .15, "analyst": .15, "macro_fit": .10}`; env `SCREENER_WEIGHTS` (JSON)
  override at module import via a `weights()` helper.
- Pillar scorers, each `def score_x(inp) -> tuple[float | None, list[str]]`
  (score 0-100 clamped, reasons with numbers baked in):
  - **value**: run_dcf (reuse app.fundamentals.dcf.run_dcf on statements+price):
    undervalued → 75 + min(25, upside_pct/2); fair → 50 ± upside/4; overvalued →
    max(5, 25 + upside/4); not_valuable → None unless forward/trailing P/E vs
    sector_pe_median available (below median → up to +15 onto a 50 base).
  - **quality**: piecewise bands averaged over available ratios from the latest
    annual row — ROE (≥20%→100, 0→0), net margin (≥20→100), gross margin
    (≥50→90), debt/equity (≤0.5→100, ≥2→0), current ratio (≥1.5→80).
  - **growth**: 3y revenue CAGR + 3y diluted-EPS CAGR mapped (≤0→ scaled 0-35,
    10%→70, ≥25%→100), averaged over available.
  - **momentum**: needs ≥ 210 closes for 200DMA else None; +40 above both
    50/200DMA (+20 one), RSI-14 (reuse signals oscillator helper or local
    implementation if import is awkward) in 45-65 → +20, >75 → −10, <30 → +10
    with contrarian reason; 3m & 6m returns positive → up to +40 scaled.
  - **analyst**: target upside pct scaled (0%→40, ≥30%→100, ≤−20%→0) ×0.6 +
    recommendation map (strong_buy 100, buy 75, hold 50, sell 25, strong_sell 0)
    ×0.4; num_analysts < 5 → shrink toward 50 by half.
  - **macro_fit**: 50 + Σ SECTOR_TILT[alert_id][sector] over fired ids, clamp
    0-100. `SECTOR_TILT: dict[str, dict[str, int]]` constant mapping each macro
    alert id to GICS-sector point tilts (e.g. claims_4wk_above_250k →
    {"Consumer Discretionary": -15, "Consumer Staples": +10}; smh_50dma →
    {"Information Technology": +10}); unmapped alert/sector → 0.
- `composite(scores) -> (float | None, coverage)`: weighted mean over non-None
  pillars; coverage = Σ available weights / Σ all weights.
- `label(composite, coverage, value, quality) -> str` (symmetric ladder):
  coverage < .5 → "hold" (+ reason "insufficient data");
  strong_buy: composite ≥ 75 and coverage ≥ .8 and value ≥ 60 and quality ≥ 60;
  buy: ≥ 60; strong_sell: < 25 and coverage ≥ .8 and value ≤ 40 and quality ≤ 40;
  sell: < 40 and coverage ≥ .6; else hold.
- `score_symbol(inp) -> dict` assembling pillar scores, composite, coverage,
  candidate, reasons (≤ 10), inputs audit blob. Deterministic: identical inputs
  → identical output (unit-tested).

## Scoring pass (job phase 4, lives in job.py or scoring.py orchestrator)

Load per-symbol inputs from DB (statements newest-4, analyst_estimates row,
closes_map, latest close as price fallback, fired alert ids via
macro_alert_state WHERE fired, sector P/E medians computed per sector from
trailing P/E of universe symbols), score all, executemany upsert
screener_scores ON CONFLICT (equity_id, score_date) DO UPDATE, then one SQL
rank update: `UPDATE screener_scores s SET rank = r.rnk FROM (SELECT id,
rank() OVER (ORDER BY composite DESC NULLS LAST, equity_id) rnk FROM
screener_scores WHERE score_date = $1) r WHERE s.id = r.id`.

## router.py — prefix /screener (JWT; mutations admin-only via user["role"])

- GET `/screener/universe?universe=sp500|ndx100|all` → members + sector.
- GET `/screener/scores?date&sector&candidate&universe&sort=composite|rank|
  value_score|...&dir=asc|desc&limit=50&offset=0` → {as_of, total, items:
  [{symbol, name, sector, composite, pillars{...}, coverage, candidate, rank,
  price, reasons}]}. Default date = latest score_date.
- GET `/screener/scores/{symbol}?days=90` → latest full row + history
  [{date, composite, candidate, rank}]; 404 unknown symbol.
- GET `/screener/candidates?side=buy|sell&limit=20&sector?` → buy:
  candidate IN (strong_buy, buy) by rank asc; sell: candidate IN (strong_sell,
  sell) by rank desc (worst first).
- GET `/screener/status` → {last_score_date, scored, universe_count, running}.
- POST `/screener/run?budget=120` (admin; 403 others) → 202 {status:"started"}
  (background task), 409 if lock held. POST `/screener/universe/refresh`
  (admin) → refresh result.
- Every list/detail response includes the disclaimer.

## Frontend — /discover page

FilterBar (universe, sector, candidate selects + sort toggle), candidates
table: rank, symbol+name, sector, composite (number + thin bar), per-pillar
mini-bars with labels, candidate Badge (strong_buy/buy hue=up tones,
sell/strong_sell down tones, hold muted), coverage %, expandable row showing
reasons[] and the score history sparkline (GET scores/{symbol}). Server-side
pagination 50/page. "Run screener" admin button calling POST /screener/run.
Nav link "Discover" after Signals. Holdings tab on /portfolio/[id] gains a
candidate Badge per row (LEFT JOIN latest scores via GET /portfolio holdings
already returning score fields — extend holdings response with
score: {composite, candidate, rank} | null).

## Conventions

Pure scorers importable without DB; ruff + strict mypy (typed locals at
cross-module boundaries: run_dcf etc.); Python 3.11-safe; tests
test_screener_{scoring,router}.py minimum per the per-file gate.
