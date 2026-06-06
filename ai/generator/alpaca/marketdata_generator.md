# Generator: Alpaca Market Data API

## Module
`backend/app/marketdata/`

## Purpose
Expose Alpaca market data — stocks, options, and news — through a clean FastAPI router.
Uses `StockHistoricalDataClient` and `OptionHistoricalDataClient` from `alpaca.data`.
No trading credentials needed; authenticates with paper or real keys if present,
falls back to unauthenticated (free/delayed feed) if neither is set.

---

## Files to Create

### `backend/app/marketdata/__init__.py`
Empty.

---

### `backend/app/marketdata/client.py`

```python
"""
Alpaca market data client factory.

Authenticates with paper keys first, then real keys, then unauthenticated
(free indicative/delayed feed). No trading credentials required.
"""
import os

try:
    from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
    _ALPACA_DATA_AVAILABLE = True
except ImportError:
    _ALPACA_DATA_AVAILABLE = False


def _get_keys() -> tuple[str | None, str | None]:
    """Return best available API key pair (paper → real → None)."""
    api_key = os.getenv("ALPACA_PAPER_API_KEY") or os.getenv("ALPACA_REAL_API_KEY")
    secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY") or os.getenv("ALPACA_REAL_SECRET_KEY")
    if api_key and secret_key:
        return api_key, secret_key
    return None, None


def get_stock_client() -> "StockHistoricalDataClient":
    if not _ALPACA_DATA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    api_key, secret_key = _get_keys()
    if api_key and secret_key:
        return StockHistoricalDataClient(api_key, secret_key)
    return StockHistoricalDataClient()  # unauthenticated — delayed/iex feed


def get_option_client() -> "OptionHistoricalDataClient":
    if not _ALPACA_DATA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    api_key, secret_key = _get_keys()
    if api_key and secret_key:
        return OptionHistoricalDataClient(api_key, secret_key)
    return OptionHistoricalDataClient()
```

---

### `backend/app/marketdata/models.py`

```python
from pydantic import BaseModel

# ── Stock models ──────────────────────────────────────────────────────────────

class Bar(BaseModel):
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None

class Quote(BaseModel):
    symbol: str
    timestamp: str
    ask_price: float | None = None
    ask_size: float | None = None
    bid_price: float | None = None
    bid_size: float | None = None

class Trade(BaseModel):
    symbol: str
    timestamp: str
    price: float
    size: float
    exchange: str | None = None

class Snapshot(BaseModel):
    symbol: str
    latest_trade: Trade | None = None
    latest_quote: Quote | None = None
    minute_bar: Bar | None = None
    daily_bar: Bar | None = None
    prev_daily_bar: Bar | None = None

class MarketMover(BaseModel):
    symbol: str
    percent_change: float
    change: float
    price: float

class MarketMovers(BaseModel):
    gainers: list[MarketMover]
    losers: list[MarketMover]

class ActiveStock(BaseModel):
    symbol: str
    volume: float | None = None
    trade_count: int | None = None
    price: float | None = None

class NewsItem(BaseModel):
    id: int
    headline: str
    summary: str | None = None
    url: str | None = None
    source: str | None = None
    author: str | None = None
    created_at: str
    updated_at: str
    symbols: list[str]

# ── Options models ────────────────────────────────────────────────────────────

class OptionGreeks(BaseModel):
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None

class OptionContract(BaseModel):
    symbol: str                   # OCC contract symbol e.g. AAPL240119C00150000
    underlying_symbol: str
    type: str                     # call | put
    strike_price: float
    expiration_date: str          # YYYY-MM-DD
    style: str | None = None      # american | european
    status: str | None = None     # active | inactive
    size: float | None = None     # contract multiplier (usually 100)

class OptionQuote(BaseModel):
    symbol: str
    timestamp: str | None = None
    bid_price: float | None = None
    bid_size: float | None = None
    ask_price: float | None = None
    ask_size: float | None = None

class OptionTrade(BaseModel):
    symbol: str
    timestamp: str | None = None
    price: float | None = None
    size: float | None = None

class OptionSnapshot(BaseModel):
    symbol: str
    latest_quote: OptionQuote | None = None
    latest_trade: OptionTrade | None = None
    implied_volatility: float | None = None
    greeks: OptionGreeks | None = None
```

---

### `backend/app/marketdata/router.py`

Prefix: `/marketdata`, tag: `marketdata`

**Helper functions:**
```python
def _data_error(e: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=str(e))

def _require_data() -> None:
    """Raise 503 if alpaca-py not installed."""
    if not _ALPACA_DATA_AVAILABLE:
        raise HTTPException(status_code=503, detail="alpaca-py package is not installed")
```

**TimeFrame mapping:**
```python
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

TIMEFRAME_MAP = {
    "1Min":   TimeFrame.Minute,
    "5Min":   TimeFrame(5, TimeFrameUnit.Minute),
    "15Min":  TimeFrame(15, TimeFrameUnit.Minute),
    "30Min":  TimeFrame(30, TimeFrameUnit.Minute),
    "1Hour":  TimeFrame.Hour,
    "1Day":   TimeFrame.Day,
    "1Week":  TimeFrame.Week,
    "1Month": TimeFrame.Month,
}
DEFAULT_TIMEFRAME = TimeFrame.Day
```

---

#### Stock Endpoints

```
GET /marketdata/stocks/{symbol}/snapshot
```
- `StockSnapshotRequest(symbol_or_symbols=[symbol.upper()])`
- `client.get_stock_snapshot(request)` → dict keyed by symbol
- Map to `Snapshot`; if symbol missing from result → 404
- Returns `Snapshot`

```
GET /marketdata/stocks/{symbol}/bars
  ?timeframe=1Day     (1Min|5Min|15Min|30Min|1Hour|1Day|1Week|1Month — invalid → 1Day)
  ?days=30            (int, 1–365, default 30)
  ?limit=1000         (int, 1–10000, default 1000)
```
- `from datetime import datetime, timedelta, UTC`
- `start = datetime.now(UTC) - timedelta(days=days)`
- `StockBarsRequest(symbol_or_symbols=[symbol.upper()], timeframe=tf, start=start, limit=limit)`
- `client.get_stock_bars(request)` → `BarSet`; iterate `result[symbol]`
- Returns `list[Bar]`

```
GET /marketdata/stocks/{symbol}/quote
```
- `StockLatestQuoteRequest(symbol_or_symbols=[symbol.upper()])`
- `client.get_stock_latest_quote(request)` → dict keyed by symbol
- Returns `Quote`

```
GET /marketdata/stocks/{symbol}/trade
```
- `StockLatestTradeRequest(symbol_or_symbols=[symbol.upper()])`
- `client.get_stock_latest_trade(request)` → dict keyed by symbol
- Returns `Trade`

```
GET /marketdata/stocks/movers?top=10
  ?top=10   (int, 1–50, default 10)
```
- `from alpaca.data.requests import MarketMoversRequest`
- `from alpaca.data.models import MarketType`
- `client.get_market_movers(MarketMoversRequest(market_type=MarketType.Stocks, top=top))`
- Map gainers and losers lists to `list[MarketMover]`
- Returns `MarketMovers`

```
GET /marketdata/stocks/active
  ?by=volume    (volume|trades, default volume)
  ?top=10       (int, 1–100, default 10)
```
- `from alpaca.data.requests import MostActivesRequest`
- `from alpaca.data.models import ActivBy` (or `ActivityType` — check SDK)
- `client.get_most_actives(MostActivesRequest(top=top, by=by_value))`
- Returns `list[ActiveStock]`

```
GET /marketdata/stocks/news
  ?symbols=AAPL,TSLA   (optional comma-separated list)
  ?limit=10            (int, 1–50, default 10)
  ?start=              (ISO date string YYYY-MM-DD, optional)
  ?end=                (ISO date string YYYY-MM-DD, optional)
```
- `from alpaca.data.requests import NewsRequest`
- Parse `symbols` param: `symbols.split(",") if symbols else None`
- `client.get_news(NewsRequest(symbols=parsed_symbols, limit=limit, start=start, end=end))`
- Returns `list[NewsItem]`

**IMPORTANT:** `/marketdata/stocks/movers`, `/marketdata/stocks/active`, and
`/marketdata/stocks/news` must be defined BEFORE `/marketdata/stocks/{symbol}/...`
routes in the router to avoid FastAPI routing `movers`/`active`/`news` as symbol values.

---

#### Options Endpoints

```
GET /marketdata/options/chain/{underlying_symbol}
  ?type=call|put           (optional)
  ?expiration=YYYY-MM-DD   (optional exact date)
  ?expiry_gte=YYYY-MM-DD   (optional)
  ?expiry_lte=YYYY-MM-DD   (optional)
  ?strike_gte=float        (optional)
  ?strike_lte=float        (optional)
  ?limit=100               (1–1000, default 100)
```
- `from alpaca.data.requests import OptionChainRequest`
- Build request with only the non-None params
- `client.get_option_chain(request)` → dict of `{symbol: OptionSnapshot}`
- Map each entry to `OptionSnapshot`
- Returns `list[OptionSnapshot]`

```
GET /marketdata/options/contracts
  ?underlying=AAPL         (optional)
  ?type=call|put            (optional)
  ?expiration=YYYY-MM-DD   (optional)
  ?expiry_gte=YYYY-MM-DD   (optional)
  ?expiry_lte=YYYY-MM-DD   (optional)
  ?strike_gte=float        (optional)
  ?strike_lte=float        (optional)
  ?status=active|inactive  (default active)
  ?limit=100               (default 100)
```
- Uses `TradingClient.get_option_contracts()` from `app.alpaca.client.get_trading_client()`
- `from alpaca.trading.requests import GetOptionContractsRequest`
- Returns `list[OptionContract]`

```
GET /marketdata/options/snapshot?symbols=AAPL240119C00150000,AAPL240119P00150000
```
- `symbols` is required query param (comma-separated OCC symbols)
- `OptionSnapshotRequest(symbol_or_symbols=symbols.split(","))`
- `client.get_option_snapshot(request)` → dict
- Returns `list[OptionSnapshot]`

```
GET /marketdata/options/quote?symbols=AAPL240119C00150000
```
- `symbols` required query param
- `OptionLatestQuoteRequest(symbol_or_symbols=symbols.split(","))`
- `client.get_option_latest_quote(request)` → dict
- Returns `list[OptionQuote]`

---

## Register in `backend/app/main.py`
```python
from app.marketdata.router import router as marketdata_router
app.include_router(marketdata_router)
```

---

## SDK Notes
- `StockHistoricalDataClient` has: `get_stock_bars`, `get_stock_latest_quote`,
  `get_stock_latest_trade`, `get_stock_snapshot`, `get_market_movers`,
  `get_most_actives`, `get_news`
- `OptionHistoricalDataClient` has: `get_option_chain`, `get_option_snapshot`,
  `get_option_latest_quote`, `get_option_latest_trade`
- Option contracts (metadata) come from `TradingClient` not the data client.
  Import `get_trading_client` from `app.alpaca.client`.
- All SDK result objects have attributes, not dict keys. Use `getattr(obj, field, None)`.
- BarSet iteration: `result[symbol]` returns a list of `Bar` SDK objects.
- `get_market_movers` returns an object with `.gainers` and `.losers` lists.
- `get_most_actives` returns an object with `.most_actives` list.
- Greeks are on the snapshot's `.greeks` attribute.
- Always uppercase symbols before passing to SDK.

---

## Test Files

### `backend/tests/test_marketdata_router.py`
Mock `app.marketdata.router.get_stock_client` and `app.marketdata.router.get_option_client`.
Minimum **22 tests**:

Stock:
- snapshot success (assert symbol + daily_bar fields)
- snapshot symbol not found → 404
- bars success with default params (assert list + OHLCV)
- bars custom timeframe (assert called with correct TimeFrame)
- bars invalid timeframe → defaults to 1Day, no error
- bars days param respected
- quote success
- trade success
- movers success (assert gainers + losers lists)
- movers top param respected
- active success by volume
- active by trades
- news with symbols filter
- news without symbols filter
- news with date range

Options:
- chain success (assert list of snapshots with symbol)
- chain with type=call filter
- chain with expiry filter
- contracts list success
- snapshot by OCC symbol
- quote by OCC symbol

General:
- any endpoint returns 503 when `_ALPACA_DATA_AVAILABLE = False`

### `backend/tests/test_marketdata_client.py`
Minimum **4 tests**:
- `get_stock_client()` returns authenticated when paper keys set
- `get_stock_client()` returns unauthenticated when no keys
- `get_option_client()` returns authenticated when real keys set
- `get_stock_client()` raises RuntimeError when alpaca-py unavailable
