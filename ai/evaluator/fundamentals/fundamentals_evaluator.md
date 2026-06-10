# Evaluator — `fundamentals` module

Checklist for the raw-statements + on-demand-metrics + live-price module. Each
item ✅/❌. All ❌ fixed before done. Pass ≥ 9.5/10 (≥ 38/40).

## OOP model (6)
- [ ] M1. `BaseFinancials` is Pydantic v2, `frozen=True`, money fields typed `int|None` (cents).
- [ ] M2. `EquityFinancials(BaseFinancials)` adds eps/shares/dividends.
- [ ] M3. `register_financials` + `_REGISTRY` + `build_financials(asset_class)` (default → equity).
- [ ] M4. Adding a new asset subclass requires NO edit to `build_financials`/any union.
- [ ] M5. `gross_margin` is a cheap `@computed_field`; heavy metrics live in the engine.
- [ ] M6. Includes current_assets/current_liabilities line items (so current_ratio works).

## Data + ingest (5)
- [ ] D1. `fetch_raw_statements` uses yfinance in `run_in_executor`; no event-loop block.
- [ ] D2. Money via `to_cents` (imported from `app.agents.data`); shares via `to_int`.
- [ ] D3. Stores RAW line items only — NO computed ratios in the DB.
- [ ] D4. Upsert `ON CONFLICT (equity_id, period_type, period_end)` is idempotent (re-run safe).
- [ ] D5. Unknown symbol → `ValueError` → router 404.

## DB schema (3)
- [ ] S1. `financial_statements` unified row per (equity_id, period_type, period_end), source default 'yfinance'.
- [ ] S2. `UNIQUE(equity_id, period_type, period_end)` + index on (equity_id, period_end DESC).
- [ ] S3. No ratio columns; reuses existing `equities` (FK).

## Metric engine (8)
- [ ] E1. Registry `@metric(name)`; `compute(requested)` invokes only requested names.
- [ ] E2. Margins (gross/operating/net), returns (roe/roa/roic), leverage (debt_to_equity/current/quick).
- [ ] E3. Growth: revenue/eps YoY + CAGR_Ny; insufficient history → None.
- [ ] E4. Valuation (pe/pb/ps/ev_ebitda) uses injected live price; price None → metric None (no error).
- [ ] E5. All metrics built on `safe_div` → None on missing/zero operand.
- [ ] E6. Negative equity → signed value (not abs, not None); documented.
- [ ] E7. `to_ttm` sums flow items over last 4 quarters, uses latest balance-sheet snapshot.
- [ ] E8. Unknown metric name → router 422 (not silent null).

## Live price / websocket (8)
- [ ] W1. `InMemoryPriceCache` implements `PriceStore`; on `app.state.price_cache`.
- [ ] W2. `FinnhubWsClient` connects with token, subscribes tracked symbols.
- [ ] W3. Subscription capped at 50 (free tier); logs warning if exceeded.
- [ ] W4. Trade messages parsed → `cache.update(symbol, price, ts_ms)`.
- [ ] W5. Exponential-backoff reconnect; graceful `stop()` on shutdown; CancelledError handled.
- [ ] W6. Missing `FINNHUB_API_KEY` → ws not started, logged (no crash).
- [ ] W7. `GET /price` returns last-known + `stale` flag; 503 only if never any tick / disabled.
- [ ] W8. Trade `t` treated as epoch milliseconds.

## API + wiring (5)
- [ ] A1. All `/fundamentals/*` routes JWT-protected (`Depends(get_current_user)`).
- [ ] A2. refresh / statements / metrics / price endpoints behave per spec.
- [ ] A3. `websockets>=12.0` in requirements; `FINNHUB_API_KEY` in .env.example + compose.
- [ ] A4. `finnhub_ok()` added to `/health`; ws task started/stopped in lifespan.
- [ ] A5. No collision with `agents` (`financial_statements` vs `fundamentals`, `/fundamentals` vs `/agents`).

## Tests & quality (5)
- [ ] T1. yfinance mocked → ingest + idempotency tested.
- [ ] T2. Metric engine over hand-built series + fixed price → each ratio, negative-equity sign, None paths.
- [ ] T3. ws parse path with fake `PriceStore` + canned trade JSON; missing-key skip tested.
- [ ] T4. Router tests (auth-bypass conftest): 422 unknown metric, price 503/stale.
- [ ] T5. ruff + strict mypy + pytest all green.
