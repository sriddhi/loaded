# Generator — `portfolio` module, BUILD + INSIGHTS (health, suggestions, composition)

Deterministic portfolio guidance on top of P1/P2: health checks, a
diversification score, sizing suggestions, and the composed insights endpoint
(holdings × screener scores × fired macro alerts × upcoming earnings). All
educational; every response carries the disclaimer; no LLM in this part.

## health.py (pure functions; constants over tables)

- `SP500_SECTOR_WEIGHTS: dict[str, float]` — 11 GICS sectors, reference index
  weights (dated comment; updated with releases).
- `run_health_checks(holdings_valued, cash_pct, latest_scores) -> list[Check]`
  where Check = {id, status: "ok"|"warn"|"flag"|"info", headline, detail,
  metric: float | None}:
  1. position_concentration — any weight > 10% warn, > 20% flag
  2. sector_overweight — portfolio sector weight − reference > 10pts warn,
     > 20pts flag (per offending sector, detail names them)
  3. min_breadth — < 5 holdings flag, < 10 warn
  4. hhi — > 0.18 flag "concentrated", 0.10-0.18 warn "moderate"
  5. cash_drag — cash > 20% of total → info
  6. score_quality — > 25% of equity value in holdings ranked sell/strong_sell
     by the latest screener scores → warn (names them)
- `diversification_score(holdings_valued) -> int 0-100`: blend — breadth
  (count/15 capped, 30%), 1−HHI scaled (30%), sector count/6 capped (25%),
  max position ≤ 10% (15%). Empty portfolio → 0.
- `suggest_allocation(cash_cents, mode, holdings_valued, candidates) ->
  list[Suggestion]`:
  - mode "equal_weight": top-up existing underweight holdings toward equal
    target weights with available cash (largest gaps first).
  - mode "score_weighted": top-N (default 5) buy/strong_buy candidates NOT
    already held, sized ∝ composite score, each capped at 10% of (portfolio
    value + cash); skip suggestions under 1 share unless fractional qty ≥ 0.1.
  - Suggestion = {symbol, action "add"|"new", suggested_qty (fractional ok,
    2dp), est_cost, target_weight_pct, reason}.

## insights.py — composition (async, reads DB; never crashes on empty)

`build_insights(pool, request-ish deps, portfolio_id) -> dict` with sections:
- holdings_signals: each holding × latest screener_scores row (composite,
  candidate, rank, reasons, weight_pct) + summary line ("N holdings rank
  sell/strong_sell"); empty list when no scores yet.
- macro_impacts: fired macro_alert_state ids joined through
  app.screener.scoring.SECTOR_TILT × the portfolio's sector weights → per
  alert {alert_id, meaning, impact, fired_since, affected: [{sector,
  portfolio_weight_pct, direction headwind|tailwind}]}; alerts whose tilts
  touch no held sector are omitted. Reuse ALERT_INFO via
  app.macro.registry for meaning/impact text.
- upcoming_earnings: earnings_calendar rows for held symbols within 14 days
  → {symbol, earnings_date, hour, weight_pct}.
- health: {diversification_score, checks} from health.py.
- as_of + disclaimer.

## Router additions (portfolio/router.py)

- GET `/portfolio/{pid}/health` → {diversification_score, checks, disclaimer}
- POST `/portfolio/{pid}/suggestions` {cash?: dollars (default portfolio cash),
  mode: "equal_weight"|"score_weighted", top_n?: 5} → {suggestions, disclaimer}
- GET `/portfolio/{pid}/insights` → the §insights.py shape
All owner-scoped (404), JWT'd.

## UI — Insights tab on /portfolio/[id]

- Health checklist (status-toned rows: flag=down, warn=warn, info/ok=muted) +
  diversification score Stat.
- Holdings-signals strip ("3 holdings now rank sell") + per-holding candidate
  chips with reasons on expand.
- Macro impacts: per fired alert — name, meaning, affected sector weights with
  headwind/tailwind badges.
- Upcoming earnings list (symbol, date, weight).
- Suggestions: mode toggle (equal weight | score weighted) + cash input +
  result rows; explicitly labeled "educational sizing illustration".

## Tests

test_portfolio_health.py (each check's thresholds incl. boundary, score bounds
0/100, suggestion caps + modes + skip-tiny, empty portfolio) and
test_portfolio_insights.py (composition with no scores / no fired alerts / no
earnings → empty sections, never raises; macro impact weight math; sell-rank
summary counts).

## Conventions

Pure where possible; cents/dollars at boundaries; typed locals at cross-module
imports; ruff + strict mypy; Python 3.11-safe.
