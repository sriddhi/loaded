"""
Unit tests for market data Pydantic models (app/marketdata/models.py).
"""

from app.marketdata.models import (
    ActiveStock,
    Bar,
    MarketMover,
    MarketMovers,
    NewsItem,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionSnapshot,
    Quote,
    Snapshot,
    Trade,
)


def test_bar_required_fields():
    b = Bar(
        symbol="AAPL",
        timestamp="2026-06-05T00:00:00Z",
        open=210.0,
        high=215.0,
        low=209.0,
        close=213.0,
        volume=50_000_000.0,
    )
    assert b.close == 213.0
    assert b.vwap is None
    assert b.trade_count is None


def test_quote_all_optional_prices():
    q = Quote(symbol="AAPL", timestamp="2026-06-05T20:00:00Z")
    assert q.ask_price is None
    assert q.bid_price is None


def test_trade_required_fields():
    t = Trade(symbol="AAPL", timestamp="2026-06-05T19:59:59Z", price=213.05, size=50.0)
    assert t.price == 213.05
    assert t.exchange is None


def test_snapshot_all_nested_optional():
    s = Snapshot(symbol="AAPL")
    assert s.latest_trade is None
    assert s.daily_bar is None


def test_market_movers_structure():
    mover = MarketMover(symbol="NVDA", percent_change=5.2, change=46.0, price=930.0)
    movers = MarketMovers(gainers=[mover], losers=[])
    assert len(movers.gainers) == 1
    assert movers.losers == []


def test_active_stock_optional_fields():
    a = ActiveStock(symbol="AAPL")
    assert a.volume is None
    assert a.trade_count is None


def test_news_item_required_fields():
    n = NewsItem(
        id=1,
        headline="Test",
        created_at="2026-06-05T10:00:00Z",
        updated_at="2026-06-05T10:05:00Z",
        symbols=["AAPL"],
    )
    assert n.id == 1
    assert n.summary is None
    assert "AAPL" in n.symbols


def test_option_greeks_all_optional():
    g = OptionGreeks()
    assert g.delta is None
    assert g.vega is None


def test_option_contract_required_fields():
    c = OptionContract(
        symbol="AAPL240620C00210000",
        underlying_symbol="AAPL",
        type="call",
        strike_price=210.0,
        expiration_date="2026-06-20",
    )
    assert c.type == "call"
    assert c.style is None


def test_option_quote_all_optional_prices():
    q = OptionQuote(symbol="AAPL240620C00210000")
    assert q.bid_price is None
    assert q.ask_price is None


def test_option_snapshot_optional_fields():
    s = OptionSnapshot(symbol="AAPL240620C00210000")
    assert s.greeks is None
    assert s.implied_volatility is None
