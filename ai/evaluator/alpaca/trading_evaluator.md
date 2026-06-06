# Evaluator: Alpaca Trading API

**Version:** 1.0 (draft — not locked)
**Scores:** pass (1) / fail (0) per check. Final = (passed / total) × 10

---

## Backend — Models (`app/alpaca/models.py`)

- [ ] `AccountInfo` has all required fields: id, status, currency, buying_power, cash, portfolio_value, pattern_day_trader, trading_blocked, account_blocked, trade_suspended_by_user, is_paper
- [ ] `Position` has all required fields: symbol, qty, side, avg_entry_price + optional current_price, market_value, unrealized_pl, unrealized_plpc, change_today
- [ ] `Order` has all required fields: id, client_order_id, symbol, qty, notional, side, type, time_in_force, limit_price, stop_price, status, filled_qty, filled_avg_price, created_at, filled_at
- [ ] `OrderRequest` validates that at least one of qty or notional is provided
- [ ] `OrderRequest` validates side is "buy" or "sell"
- [ ] `OrderRequest` validates type is one of: market, limit, stop, stop_limit
- [ ] `PortfolioSnapshot` has: timestamps, equity, profit_loss, profit_loss_pct, base_value, timeframe
- [ ] `MarketClock` has: timestamp, is_open, next_open, next_close
- [ ] All float fields use `float`, not `Decimal` (consistency with rest of codebase)
- [ ] All optional fields typed as `X | None`, not `Optional[X]`

## Backend — Client (`app/alpaca/client.py`)

- [ ] `get_trading_client()` reads `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` from env
- [ ] `get_trading_client()` raises `RuntimeError` (not `ValueError` or bare `Exception`) when credentials missing
- [ ] `paper_trading_enabled()`, `alpaca_configured()`, `alpaca_ok()` are all present (backward compat)
- [ ] `alpaca-py` import is guarded with `try/except ImportError` + `_ALPACA_AVAILABLE` flag
- [ ] `get_trading_client()` does NOT cache the client at module level
- [ ] No hardcoded API keys or URLs anywhere in the file

## Backend — Router (`app/alpaca/router.py`)

- [ ] Router prefix is `/alpaca`, tag is `"alpaca"`
- [ ] All 10 endpoints exist: GET /account, GET /account/clock, GET /positions, GET /positions/{symbol}, DELETE /positions/{symbol}, GET /orders, POST /orders, GET /orders/{order_id}, DELETE /orders/{order_id}, GET /portfolio/history
- [ ] Every endpoint calls `get_trading_client()` inside the handler (not at import/module level)
- [ ] Every Alpaca SDK call is wrapped in `try/except`
- [ ] Not-configured case returns HTTP 503 (not 401 or 500)
- [ ] Alpaca `APIError` returns HTTP 502 (not 500)
- [ ] Not-found cases (position, order) return HTTP 404
- [ ] `POST /alpaca/orders` with both `qty` and `notional` set returns HTTP 422
- [ ] All `raise HTTPException(...) from e` — no bare raises in except blocks
- [ ] Raw Alpaca SDK objects are never returned directly — always converted to Pydantic models
- [ ] `GET /alpaca/orders` accepts `status` query param with default "open"
- [ ] `GET /alpaca/orders` accepts `limit` query param with default 50
- [ ] `GET /alpaca/portfolio/history` accepts `period` (default "1M") and `timeframe` (default "1D")
- [ ] Router is registered in `main.py`

## Backend — Tests (`tests/test_alpaca_trading.py`)

- [ ] File exists at `backend/tests/test_alpaca_trading.py`
- [ ] All 18 tests are present (see generator spec for full list)
- [ ] Zero real API calls — all Alpaca SDK calls are mocked with `unittest.mock.patch`
- [ ] Tests pass without `ALPACA_API_KEY` or `ALPACA_SECRET_KEY` in environment
- [ ] `test_get_account_not_configured` passes — env vars absent → HTTP 503
- [ ] `test_get_account_api_error` passes — SDK raises → HTTP 502
- [ ] `test_place_order_qty_and_notional_both_set` passes → HTTP 422
- [ ] `test_get_position_not_found` passes → HTTP 404
- [ ] `test_cancel_order_not_found` passes → HTTP 404
- [ ] All tests use `pytest` (not unittest.TestCase)
- [ ] No `time.sleep` or real network calls anywhere in the test file
- [ ] `pytest backend/tests/test_alpaca_trading.py -v` exits 0

## Code Quality

- [ ] `ruff format --check backend/` passes
- [ ] `ruff check backend/` passes (no import order, unused imports, or B904 violations)
- [ ] `mypy backend/app/ --explicit-package-bases --ignore-missing-imports` passes
- [ ] All new functions have return type annotations
- [ ] No `Any` return types without explicit `-> dict[str, Any]` annotation
- [ ] `__init__.py` exists in `backend/app/alpaca/`

## Integration

- [ ] `GET /alpaca/account` returns 503 (not 500 or connection error) when credentials not in `.env`
- [ ] `GET /health` still works after changes — existing `app.alpaca_client` import not broken
- [ ] Existing tests (`test_alpaca_connectivity.py`) still pass — backward compat preserved
- [ ] `docker compose build backend` succeeds with no new errors

---

## Scoring

| Range | Grade |
|-------|-------|
| 9.5–10 | Ship it |
| 8.0–9.4 | Fix failures then ship |
| < 8.0 | Do not ship — fix all ❌ |
