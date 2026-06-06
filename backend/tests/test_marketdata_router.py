"""
Unit tests for market data endpoints.

All Alpaca SDK calls are mocked — no real network calls required.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

# ── Mock helpers ───────────────────────────────────────────────────────────────

MOCK_BAR = SimpleNamespace(
    timestamp="2026-06-05T00:00:00Z",
    open=210.0,
    high=215.0,
    low=209.0,
    close=213.0,
    volume=50_000_000.0,
    vwap=212.5,
    trade_count=450_000,
)

MOCK_QUOTE = SimpleNamespace(
    timestamp="2026-06-05T20:00:00Z",
    ask_price=213.10,
    ask_size=100.0,
    bid_price=213.00,
    bid_size=200.0,
)

MOCK_TRADE = SimpleNamespace(
    timestamp="2026-06-05T19:59:59Z",
    price=213.05,
    size=50.0,
    exchange="Q",
)

MOCK_SNAPSHOT = SimpleNamespace(
    latest_trade=MOCK_TRADE,
    latest_quote=MOCK_QUOTE,
    minute_bar=MOCK_BAR,
    daily_bar=MOCK_BAR,
    previous_daily_bar=MOCK_BAR,
)

MOCK_MOVER = SimpleNamespace(symbol="NVDA", percent_change=5.2, change=46.0, price=930.0)
MOCK_MOVERS = SimpleNamespace(gainers=[MOCK_MOVER], losers=[MOCK_MOVER])

MOCK_ACTIVE = SimpleNamespace(symbol="AAPL", volume=80_000_000.0, trade_count=600_000, price=213.0)
MOCK_ACTIVES = SimpleNamespace(most_actives=[MOCK_ACTIVE])

MOCK_NEWS = SimpleNamespace(
    id=1,
    headline="Apple beats earnings",
    summary="Apple reported strong Q2.",
    url="https://example.com/news/1",
    source="Benzinga",
    author="Jane Doe",
    created_at="2026-06-05T10:00:00Z",
    updated_at="2026-06-05T10:05:00Z",
    symbols=["AAPL"],
)

MOCK_GREEKS = SimpleNamespace(delta=0.55, gamma=0.02, theta=-0.05, vega=0.30, rho=0.01)
MOCK_OPTION_QUOTE = SimpleNamespace(
    timestamp="2026-06-05T20:00:00Z",
    bid_price=3.10,
    bid_size=10.0,
    ask_price=3.20,
    ask_size=10.0,
)
MOCK_OPTION_TRADE = SimpleNamespace(timestamp="2026-06-05T19:59:00Z", price=3.15, size=5.0)
MOCK_OPTION_SNAP = SimpleNamespace(
    latest_quote=MOCK_OPTION_QUOTE,
    latest_trade=MOCK_OPTION_TRADE,
    implied_volatility=0.28,
    greeks=MOCK_GREEKS,
)


def _stock_client(
    snapshot=None, bars=None, quote=None, trade=None, movers=None, actives=None, news=None
):
    m = MagicMock()
    if snapshot is not None:
        m.get_stock_snapshot.return_value = snapshot
    if bars is not None:
        m.get_stock_bars.return_value = bars
    if quote is not None:
        m.get_stock_latest_quote.return_value = quote
    if trade is not None:
        m.get_stock_latest_trade.return_value = trade
    if movers is not None:
        m.get_market_movers.return_value = movers
    if actives is not None:
        m.get_most_actives.return_value = actives
    if news is not None:
        m.get_news.return_value = news
    return m


# ── Stock: snapshot ────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_stock_client")
def test_snapshot_success(mock_get):
    mock_get.return_value = _stock_client(snapshot={"AAPL": MOCK_SNAPSHOT})
    resp = client.get("/marketdata/stocks/AAPL/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["daily_bar"]["close"] == 213.0
    assert data["latest_quote"]["ask_price"] == 213.10


@patch("app.marketdata.router.get_stock_client")
def test_snapshot_not_found(mock_get):
    mock_get.return_value = _stock_client(snapshot={})
    resp = client.get("/marketdata/stocks/FAKE/snapshot")
    assert resp.status_code == 404


# ── Stock: bars ────────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_stock_client")
def test_bars_success(mock_get):
    bars_result = MagicMock()
    bars_result.get.return_value = [MOCK_BAR, MOCK_BAR]
    mock_get.return_value = _stock_client(bars=bars_result)
    resp = client.get("/marketdata/stocks/AAPL/bars")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["open"] == 210.0
    assert data[0]["close"] == 213.0


@patch("app.marketdata.router.get_stock_client")
def test_bars_custom_timeframe(mock_get):
    bars_result = MagicMock()
    bars_result.get.return_value = [MOCK_BAR]
    mock_get.return_value = _stock_client(bars=bars_result)
    resp = client.get("/marketdata/stocks/AAPL/bars?timeframe=1Hour&days=7")
    assert resp.status_code == 200


@patch("app.marketdata.router.get_stock_client")
def test_bars_invalid_timeframe_defaults_gracefully(mock_get):
    bars_result = MagicMock()
    bars_result.get.return_value = [MOCK_BAR]
    mock_get.return_value = _stock_client(bars=bars_result)
    resp = client.get("/marketdata/stocks/AAPL/bars?timeframe=BOGUS")
    assert resp.status_code == 200  # invalid → defaults to 1Day, no error


# ── Stock: quote ───────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_stock_client")
def test_quote_success(mock_get):
    mock_get.return_value = _stock_client(quote={"AAPL": MOCK_QUOTE})
    resp = client.get("/marketdata/stocks/AAPL/quote")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["ask_price"] == 213.10
    assert data["bid_price"] == 213.00


@patch("app.marketdata.router.get_stock_client")
def test_quote_not_found(mock_get):
    mock_get.return_value = _stock_client(quote={})
    resp = client.get("/marketdata/stocks/FAKE/quote")
    assert resp.status_code == 404


# ── Stock: trade ───────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_stock_client")
def test_trade_success(mock_get):
    mock_get.return_value = _stock_client(trade={"AAPL": MOCK_TRADE})
    resp = client.get("/marketdata/stocks/AAPL/trade")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["price"] == 213.05


# ── Stock: movers ──────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_screener_client")
def test_movers_success(mock_get):
    m = MagicMock()
    m.get_market_movers.return_value = MOCK_MOVERS
    mock_get.return_value = m
    resp = client.get("/marketdata/stocks/movers")
    assert resp.status_code == 200
    data = resp.json()
    assert "gainers" in data
    assert "losers" in data
    assert data["gainers"][0]["symbol"] == "NVDA"
    assert data["gainers"][0]["percent_change"] == 5.2


@patch("app.marketdata.router.get_screener_client")
def test_movers_top_param(mock_get):
    m = MagicMock()
    m.get_market_movers.return_value = MOCK_MOVERS
    mock_get.return_value = m
    resp = client.get("/marketdata/stocks/movers?top=5")
    assert resp.status_code == 200


# ── Stock: active ──────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_screener_client")
def test_active_by_volume(mock_get):
    m = MagicMock()
    m.get_most_actives.return_value = MOCK_ACTIVES
    mock_get.return_value = m
    resp = client.get("/marketdata/stocks/active?by=volume")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL"
    assert data[0]["volume"] == 80_000_000.0


@patch("app.marketdata.router.get_screener_client")
def test_active_by_trades(mock_get):
    m = MagicMock()
    m.get_most_actives.return_value = MOCK_ACTIVES
    mock_get.return_value = m
    resp = client.get("/marketdata/stocks/active?by=trades")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["trade_count"] == 600_000


# ── Stock: news ────────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_news_client")
def test_news_with_symbols(mock_get):
    m = MagicMock()
    m.get_news.return_value = [MOCK_NEWS]
    mock_get.return_value = m
    resp = client.get("/marketdata/stocks/news?symbols=AAPL&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["headline"] == "Apple beats earnings"
    assert "AAPL" in data[0]["symbols"]
    assert m.get_news.call_args is not None


@patch("app.marketdata.router.get_news_client")
def test_news_without_symbols(mock_get):
    m = MagicMock()
    m.get_news.return_value = [MOCK_NEWS]
    mock_get.return_value = m
    resp = client.get("/marketdata/stocks/news")
    assert resp.status_code == 200


@patch("app.marketdata.router.get_news_client")
def test_news_with_date_range(mock_get):
    m = MagicMock()
    m.get_news.return_value = [MOCK_NEWS]
    mock_get.return_value = m
    resp = client.get("/marketdata/stocks/news?start=2026-06-01&end=2026-06-05")
    assert resp.status_code == 200


# ── Options: chain ─────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_option_client")
def test_option_chain_success(mock_get):
    m = MagicMock()
    m.get_option_chain.return_value = {"AAPL240620C00210000": MOCK_OPTION_SNAP}
    mock_get.return_value = m
    resp = client.get("/marketdata/options/chain/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL240620C00210000"
    assert data[0]["implied_volatility"] == 0.28


@patch("app.marketdata.router.get_option_client")
def test_option_chain_with_type_filter(mock_get):
    m = MagicMock()
    m.get_option_chain.return_value = {"AAPL240620C00210000": MOCK_OPTION_SNAP}
    mock_get.return_value = m
    resp = client.get("/marketdata/options/chain/AAPL?type=call")
    assert resp.status_code == 200


@patch("app.marketdata.router.get_option_client")
def test_option_chain_with_expiry_filter(mock_get):
    m = MagicMock()
    m.get_option_chain.return_value = {}
    mock_get.return_value = m
    resp = client.get("/marketdata/options/chain/AAPL?expiry_gte=2026-06-01&expiry_lte=2026-06-30")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Options: snapshot ──────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_option_client")
def test_option_snapshot_success(mock_get):
    m = MagicMock()
    m.get_option_snapshot.return_value = {"AAPL240620C00210000": MOCK_OPTION_SNAP}
    mock_get.return_value = m
    resp = client.get("/marketdata/options/snapshot?symbols=AAPL240620C00210000")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["implied_volatility"] == 0.28
    assert data[0]["greeks"]["delta"] == 0.55


# ── Options: quote ─────────────────────────────────────────────────────────────


@patch("app.marketdata.router.get_option_client")
def test_option_quote_success(mock_get):
    m = MagicMock()
    m.get_option_latest_quote.return_value = {"AAPL240620C00210000": MOCK_OPTION_QUOTE}
    mock_get.return_value = m
    resp = client.get("/marketdata/options/quote?symbols=AAPL240620C00210000")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["symbol"] == "AAPL240620C00210000"
    assert data[0]["ask_price"] == 3.20


# ── 503 when alpaca-py unavailable ────────────────────────────────────────────


@patch("app.marketdata.router._ALPACA_DATA_AVAILABLE", False)
def test_stock_snapshot_503_when_unavailable():
    resp = client.get("/marketdata/stocks/AAPL/snapshot")
    assert resp.status_code == 503
    assert "alpaca-py" in resp.json()["detail"]


@patch("app.marketdata.router._ALPACA_DATA_AVAILABLE", False)
def test_option_chain_503_when_unavailable():
    resp = client.get("/marketdata/options/chain/AAPL")
    assert resp.status_code == 503
