# Generator: Alpaca Trading API

**Version:** 1.0 (draft — not locked)
**Module:** `backend/app/alpaca/`
**Scope:** Full read/write trading API endpoints + unit tests

---

## What to Build

Extend the existing Alpaca integration from health-check-only to a full trading API. Supports both paper and live accounts — the environment variable `ALPACA_PAPER_TRADE` already controls which endpoint is used.

---

## New Files

```
backend/app/alpaca/
    __init__.py
    client.py        ← replace top-level alpaca_client.py (keep backward compat)
    models.py        ← Pydantic request/response models
    router.py        ← FastAPI router, prefix=/alpaca

backend/tests/
    test_alpaca_trading.py   ← unit tests (all mocked, no real API calls)
```

---

## 1. `backend/app/alpaca/client.py`

Singleton factory that returns a configured `TradingClient`. Keep backward compatibility with `app.alpaca_client` module (other files import from it).

```python
# Public interface
def get_trading_client() -> TradingClient
def alpaca_configured() -> bool           # keep — used by health endpoint
def alpaca_ok() -> tuple[bool, str | None] # keep — used by health endpoint
def paper_trading_enabled() -> bool        # keep
```

Implementation rules:
- `get_trading_client()` reads `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER_TRADE` from env
- Raises `RuntimeError("Alpaca credentials not configured")` if keys missing
- Does NOT cache the client instance (stateless, safe for async)
- Guard the `alpaca-py` import with `try/except ImportError` (already done in current file — keep this pattern)

---

## 2. `backend/app/alpaca/models.py`

Pydantic models for API responses. All fields optional-safe (Alpaca returns None for some fields when account is in restricted state).

```python
class AccountInfo(BaseModel):
    id: str
    status: str                    # ACTIVE | ACCOUNT_UPDATED | ONBOARDING | etc.
    currency: str                  # USD
    buying_power: float
    cash: float
    portfolio_value: float
    pattern_day_trader: bool
    trading_blocked: bool
    account_blocked: bool
    trade_suspended_by_user: bool
    is_paper: bool                 # derived from ALPACA_PAPER_TRADE env var

class Position(BaseModel):
    symbol: str
    qty: float
    side: str                      # long | short
    avg_entry_price: float
    current_price: float | None
    market_value: float | None
    unrealized_pl: float | None
    unrealized_plpc: float | None  # percent
    change_today: float | None

class Order(BaseModel):
    id: str
    client_order_id: str
    symbol: str
    qty: float | None
    notional: float | None
    side: str                      # buy | sell
    type: str                      # market | limit | stop | stop_limit
    time_in_force: str             # day | gtc | ioc | fok
    limit_price: float | None
    stop_price: float | None
    status: str                    # new | partially_filled | filled | canceled | etc.
    filled_qty: float | None
    filled_avg_price: float | None
    created_at: str
    filled_at: str | None

class OrderRequest(BaseModel):
    symbol: str
    qty: float | None = None       # qty OR notional required, not both
    notional: float | None = None
    side: str                      # buy | sell
    type: str = "market"           # market | limit | stop | stop_limit
    time_in_force: str = "day"     # day | gtc | ioc | fok
    limit_price: float | None = None
    stop_price: float | None = None

class PortfolioSnapshot(BaseModel):
    timestamps: list[int]          # unix timestamps
    equity: list[float]
    profit_loss: list[float]
    profit_loss_pct: list[float]
    base_value: float
    timeframe: str

class MarketClock(BaseModel):
    timestamp: str
    is_open: bool
    next_open: str
    next_close: str
```

---

## 3. `backend/app/alpaca/router.py`

FastAPI router. Prefix: `/alpaca`. All endpoints return clean Pydantic models, never raw Alpaca SDK objects.

```
GET  /alpaca/account                → AccountInfo
GET  /alpaca/account/clock          → MarketClock
GET  /alpaca/positions              → list[Position]
GET  /alpaca/positions/{symbol}     → Position
DELETE /alpaca/positions/{symbol}   → {"message": "Position closed", "order": Order}
GET  /alpaca/orders                 → list[Order]   ?status=open|closed|all  ?limit=50
POST /alpaca/orders                 → Order         (body: OrderRequest)
GET  /alpaca/orders/{order_id}      → Order
DELETE /alpaca/orders/{order_id}    → {"message": "Order cancelled"}
GET  /alpaca/portfolio/history      → PortfolioSnapshot  ?period=1D|1W|1M|3M|1A&timeframe=1Min|5Min|1H|1D
```

Error handling rules:
- Alpaca not configured → `HTTP 503` with `{"detail": "Alpaca credentials not configured"}`
- Alpaca SDK raises `APIError` → `HTTP 502` with `{"detail": "<alpaca error message>"}`
- Symbol not found / order not found → `HTTP 404`
- Invalid order parameters (e.g. both qty and notional) → `HTTP 422`
- All `raise HTTPException(...) from e` — B904 pattern

Implementation rules:
- Call `get_trading_client()` inside each endpoint handler (not at import time)
- Wrap every Alpaca SDK call in `try/except` — never let SDK exceptions leak
- Convert Alpaca SDK model objects to Pydantic models explicitly (don't rely on dict coercion)
- `DELETE /alpaca/positions/{symbol}` calls `client.close_position(symbol)` — returns the closing order
- `GET /alpaca/orders` accepts `status` query param: map to Alpaca's `QueryOrderStatus` enum
- `GET /alpaca/portfolio/history` accepts `period` and `timeframe` query params with sensible defaults (`1M`, `1D`)

---

## 4. Register Router in `main.py`

Add to `backend/app/main.py`:

```python
from app.alpaca.router import router as alpaca_router
app.include_router(alpaca_router)
```

---

## 5. `backend/tests/test_alpaca_trading.py`

All tests use `unittest.mock.patch` — no real API calls, no credentials required.

### Test coverage required:

**Account tests:**
- `test_get_account_success` — mock `get_account()`, assert AccountInfo fields mapped correctly
- `test_get_account_not_configured` — env vars missing, assert HTTP 503
- `test_get_account_api_error` — mock raises `APIError`, assert HTTP 502
- `test_get_market_clock` — mock `get_clock()`, assert MarketClock fields

**Position tests:**
- `test_get_positions_empty` — mock returns `[]`, assert response is `[]`
- `test_get_positions_with_data` — mock returns 2 positions, assert list length + field mapping
- `test_get_position_by_symbol` — mock `get_open_position("AAPL")`, assert Position fields
- `test_get_position_not_found` — mock raises `APIError` with 404 code, assert HTTP 404
- `test_close_position` — mock `close_position("AAPL")`, assert response contains closing order

**Order tests:**
- `test_get_orders_all` — mock `get_orders()`, assert list of Order
- `test_get_orders_open_status` — assert status=open maps to correct Alpaca enum
- `test_place_market_order` — body: `{symbol, qty, side="buy", type="market"}`, assert Order returned
- `test_place_limit_order` — body includes `limit_price`, assert mapped correctly
- `test_place_order_qty_and_notional_both_set` — assert HTTP 422
- `test_place_order_not_configured` — env missing, assert HTTP 503
- `test_cancel_order` — mock `cancel_order_by_id(id)`, assert 200 + message
- `test_cancel_order_not_found` — mock raises, assert HTTP 404

**Portfolio history tests:**
- `test_portfolio_history_default_params` — assert default period=1M, timeframe=1D
- `test_portfolio_history_custom_params` — period=1W, timeframe=1H

**Total: 18 tests minimum. All must pass with no credentials in environment.**

---

## What NOT to Do

- Do NOT cache the `TradingClient` instance as a module-level singleton — it reads env vars at call time which is important for test isolation
- Do NOT return raw Alpaca SDK objects from endpoints — always convert to Pydantic models
- Do NOT import from the old top-level `app.alpaca_client` in the new router — use `app.alpaca.client`
- Do NOT add websocket/streaming endpoints — out of scope for this feature
- Do NOT add watchlist endpoints — out of scope
- Do NOT implement order modification (`replace_order_by_id`) — too complex for v1, add in v2
- Do NOT remove `app/alpaca_client.py` — health endpoint and tests still import from it; keep it, just don't extend it
