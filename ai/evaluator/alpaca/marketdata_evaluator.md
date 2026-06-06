# Evaluator: Alpaca Market Data API

Threshold to ship: **9.5 / 10**

Score each check: ✅ pass (1.0) | ⚠️ partial (0.5) | ❌ fail (0)

---

## Models (12 checks)

- [ ] `Bar`: symbol, timestamp, open, high, low, close, volume required; vwap + trade_count optional
- [ ] `Quote`: symbol, timestamp required; ask_price, ask_size, bid_price, bid_size all optional floats
- [ ] `Trade`: symbol, timestamp, price, size required; exchange optional
- [ ] `Snapshot`: symbol required; latest_trade, latest_quote, minute_bar, daily_bar, prev_daily_bar all optional
- [ ] `MarketMover`: symbol, percent_change, change, price all required floats
- [ ] `MarketMovers`: gainers and losers as `list[MarketMover]`
- [ ] `ActiveStock`: symbol required; volume, trade_count, price optional
- [ ] `NewsItem`: id, headline, created_at, updated_at, symbols required; others optional
- [ ] `OptionGreeks`: all 5 greeks (delta, gamma, theta, vega, rho) optional floats
- [ ] `OptionContract`: symbol, underlying_symbol, type, strike_price, expiration_date required; style, status, size optional
- [ ] `OptionQuote`: symbol required; bid/ask price+size optional; timestamp optional
- [ ] `OptionSnapshot`: symbol required; latest_quote, latest_trade, implied_volatility, greeks all optional

---

## Client (6 checks)

- [ ] `try/except ImportError` guard at module level; `_ALPACA_DATA_AVAILABLE` flag set correctly
- [ ] `_get_keys()` helper tries paper keys first, then real keys
- [ ] `get_stock_client()` returns authenticated client when any keys present
- [ ] `get_stock_client()` returns unauthenticated client (no crash) when no keys
- [ ] `get_option_client()` mirrors same pattern as stock client
- [ ] Both factories raise `RuntimeError("alpaca-py package is not installed")` when unavailable

---

## Router (22 checks)

- [ ] Prefix `/marketdata`, tag `marketdata`
- [ ] Static routes (`/stocks/movers`, `/stocks/active`, `/stocks/news`) defined BEFORE `/{symbol}` routes
- [ ] `GET /marketdata/stocks/{symbol}/snapshot` → `Snapshot`; 404 if symbol missing from result
- [ ] `GET /marketdata/stocks/{symbol}/bars` accepts timeframe, days (1–365), limit params
- [ ] bars: invalid timeframe string silently defaults to `1Day` (no 422 error)
- [ ] bars: start datetime computed as `now(UTC) - timedelta(days=days)`
- [ ] `GET /marketdata/stocks/{symbol}/quote` → `Quote`
- [ ] `GET /marketdata/stocks/{symbol}/trade` → `Trade`
- [ ] `GET /marketdata/stocks/movers` → `MarketMovers` with gainers + losers; top param (1–50)
- [ ] `GET /marketdata/stocks/active` → `list[ActiveStock]`; by param (volume|trades); top param (1–100)
- [ ] `GET /marketdata/stocks/news` → `list[NewsItem]`; symbols comma-parsed; limit (1–50)
- [ ] news: start/end params are optional and passed to SDK only when provided
- [ ] `GET /marketdata/options/chain/{underlying_symbol}` → `list[OptionSnapshot]`; all filters optional
- [ ] chain: type, expiration, expiry_gte/lte, strike_gte/lte params wired to SDK request
- [ ] `GET /marketdata/options/contracts` → `list[OptionContract]`; uses TradingClient (not data client)
- [ ] contracts: underlying, type, expiry, strike, status params all optional
- [ ] `GET /marketdata/options/snapshot` → `list[OptionSnapshot]`; symbols required query param
- [ ] `GET /marketdata/options/quote` → `list[OptionQuote]`; symbols required query param
- [ ] All endpoints return 502 on SDK/API errors (not bare 500)
- [ ] All endpoints return 503 when alpaca-py not installed
- [ ] All symbols uppercased before passing to SDK
- [ ] `marketdata_router` registered in `main.py`

---

## Tests (14 checks)

- [ ] `test_marketdata_router.py` exists with ≥ 22 tests
- [ ] `test_marketdata_client.py` exists with ≥ 4 tests
- [ ] All tests mock client factory — no real network calls
- [ ] snapshot success asserts symbol and at least one bar field
- [ ] snapshot 404 test: SDK returns empty dict for symbol
- [ ] bars test asserts list length and open/close fields
- [ ] invalid timeframe test: request succeeds and returns bars (not 422)
- [ ] movers test asserts `gainers` and `losers` keys, each a list
- [ ] active test asserts list with symbol field; tests both `by=volume` and `by=trades`
- [ ] news with symbols asserts correct symbols list passed to SDK
- [ ] chain test asserts list of snapshots each with symbol field
- [ ] contracts test asserts list of OptionContract with required fields
- [ ] option snapshot test asserts symbol + greeks or implied_volatility present
- [ ] 503 test: mock `_ALPACA_DATA_AVAILABLE = False`, verify 503 on a stock and option endpoint

---

## Code Quality (6 checks)

- [ ] ruff format passes with 0 changes
- [ ] ruff lint passes with 0 errors
- [ ] mypy passes with 0 errors across all new files
- [ ] No bare `except:` — always `except Exception as e:`
- [ ] All router functions have explicit return type annotations
- [ ] No hardcoded API keys or feed values in source code
