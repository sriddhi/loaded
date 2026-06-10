# Generator — `fundamentals` module (raw statements + on-demand metrics + live price)

**Module:** `fundamentals` (`backend/app/fundamentals/**`)
**Mounts at:** `/fundamentals` (distinct from the existing `agents` → `/agents`)

## Purpose
Store **raw** financial-statement line items (from **yfinance**, free) and compute
financial **metrics on demand**. Stream **live price** from the **Finnhub
websocket** (free tier). Generic OOP base model + an `EquityFinancials` subclass,
extensible to ETF/crypto/bank later without refactor.

## Decisions (fixed)
- Statements ← yfinance (full line items). Live price ← Finnhub ws (`wss://ws.finnhub.io?token=KEY`).
- Money stored as **integer cents** (BIGINT); ratios/prices float. Reuse
  `to_cents` / `to_int` / `safe_div` / `_get` from `app.agents.data`.
- Metrics are **computed on demand**, never stored.
- Coexists with `agents` (keeps `fundamentals` table + `/agents/*`). New table is
  `financial_statements`; no route/table collision.
- No MCP/skills now.

## Files to create (`backend/app/fundamentals/`)
- `__init__.py`
- `models.py` — Pydantic v2 `BaseFinancials(frozen=True)` (period metadata +
  common line items in cents: revenue, cogs, gross_profit, operating_income,
  net_income, ebitda, total_assets, total_liabilities, total_equity, total_debt,
  cash_and_equiv, current_assets, current_liabilities, operating_cash_flow,
  capex, free_cash_flow; one `@computed_field gross_margin`).
  `EquityFinancials(BaseFinancials)` adds eps_basic, eps_diluted, shares_basic,
  shares_diluted, shares_outstanding, dividends_paid. A registry
  `_REGISTRY: dict[str, type[BaseFinancials]]` + `register_financials(cls)` +
  `build_financials(asset_class, **fields)` (default → equity). Plus request/
  response models. **Subclassing + registry, NOT a discriminated union.**
- `data.py` — `async fetch_raw_statements(symbol) -> list[dict]`: yfinance in
  `run_in_executor`; extract income/balance/cashflow line items (no ratio math);
  cents via `to_cents`. Raises `ValueError` on unknown symbol.
- `ingest.py` — `async ingest_statements(symbol, conn) -> dict`: upsert raw rows
  into `financial_statements`, `ON CONFLICT (equity_id, period_type, period_end)
  DO UPDATE SET col = COALESCE(EXCLUDED.col, …)`. Idempotent. Upserts `equities`.
- `metrics.py` — `MetricContext(series, live_price)`; metric registry via
  `@metric(name)`; `FundamentalMetrics.compute(requested) -> dict[str,float|None]`.
  Metrics: gross/operating/net margin, roe/roa/roic, debt_to_equity,
  current_ratio, quick_ratio, revenue/eps YoY, revenue/eps CAGR_Ny, pe/pb/ps/
  ev_ebitda (valuation needs injected live price). `to_ttm(series)` helper. All
  on `safe_div` (None-safe). Negative equity → signed value. Insufficient history
  → None.
- `price_cache.py` — `PriceStore` Protocol + `InMemoryPriceCache`
  (`dict[str,(price,ts_ms)]` + `asyncio.Lock`). Stored on `app.state.price_cache`.
- `finnhub_ws.py` — `FinnhubWsClient(api_key, cache, symbols)` using `websockets`:
  connect+subscribe (cap **50** symbols, log if exceeded), parse
  `{"type":"trade","data":[{s,p,t,v}]}` → `cache.update`, exponential-backoff
  reconnect, graceful `stop()`. `finnhub_ws_enabled()` → False if no
  `FINNHUB_API_KEY` (skip starting). `t` is epoch **milliseconds**.
- `client.py` — `finnhub_ok() -> tuple[bool,str|None]` for `/health`
  (ws-connected flag; `(False,"missing_credentials")` if key absent).
- `router.py` — `APIRouter(prefix="/fundamentals")`, all JWT-protected:
  - `POST /{symbol}/refresh` → fetch+upsert; `{symbol, periods_written, elapsed_ms}`.
  - `GET /{symbol}/statements?period=annual|quarterly&type=income|balance|cashflow|all`
    → stored rows as `EquityFinancials`. 404 if absent.
  - `GET /{symbol}/metrics?metrics=pe,roe,…&period=annual|quarterly|ttm` →
    compute on demand; valuation reads live price from cache; **unknown metric
    name → 422**; response includes `price_used`.
  - `GET /{symbol}/price` → last-known cached price + `ts` + `stale` flag;
    **503 only if no tick ever / ws disabled** (not every night).

## Modify
- `backend/app/main.py` — append `financial_statements` DDL to `DB_MIGRATIONS`
  (unified row per (equity_id, period_type, period_end), raw cents columns +
  equity-specific + current_assets/current_liabilities, `UNIQUE`, index on
  `(equity_id, period_end DESC)`, source default 'yfinance', NO ratio columns);
  include `fundamentals_router` with `_auth_dep`; start/stop ws task in lifespan;
  add `"finnhub"` to `/health`.
- `backend/requirements.txt` — add `websockets>=12.0`.
- `.env.example` + `docker-compose.yml` — `FINNHUB_API_KEY`.

## Constraints
- ruff + strict mypy + pytest green; every function fully type-annotated.
- yfinance flakiness/schema drift → many None metrics acceptable; COALESCE upsert
  preserves prior values. Markets closed → no ticks → `/price` returns stale, not error.
