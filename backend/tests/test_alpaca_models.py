"""
Unit tests for Alpaca Pydantic models (app/alpaca/models.py).
"""

from app.alpaca.models import (
    AccountInfo,
    MarketClock,
    OrderRequest,
    PortfolioSnapshot,
    Position,
)


def test_account_info_fields():
    a = AccountInfo(
        id="abc",
        status="ACTIVE",
        currency="USD",
        buying_power=10000.0,
        cash=5000.0,
        portfolio_value=15000.0,
        pattern_day_trader=False,
        trading_blocked=False,
        account_blocked=False,
        trade_suspended_by_user=False,
        is_paper=True,
    )
    assert a.id == "abc"
    assert a.is_paper is True


def test_position_optional_fields_none():
    p = Position(
        symbol="AAPL",
        qty=10.0,
        side="long",
        avg_entry_price=200.0,
        current_price=None,
        market_value=None,
        unrealized_pl=None,
        unrealized_plpc=None,
        change_today=None,
    )
    assert p.current_price is None


def test_order_defaults():
    req = OrderRequest(symbol="AAPL", qty=5.0, side="buy")
    assert req.type == "market"
    assert req.time_in_force == "day"
    assert req.notional is None


def test_order_requires_either_qty_or_notional():
    # pydantic allows both None at model level; validation is in the router
    req = OrderRequest(symbol="AAPL", side="buy")
    assert req.qty is None
    assert req.notional is None


def test_portfolio_snapshot_empty_lists():
    snap = PortfolioSnapshot(
        timestamps=[],
        equity=[],
        profit_loss=[],
        profit_loss_pct=[],
        base_value=0.0,
        timeframe="1D",
    )
    assert snap.equity == []


def test_market_clock_fields():
    clock = MarketClock(
        timestamp="2026-06-06T09:30:00",
        is_open=True,
        next_open="2026-06-09T09:30:00",
        next_close="2026-06-06T16:00:00",
    )
    assert clock.is_open is True
