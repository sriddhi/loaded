"""Hand-computed fixtures for the pure portfolio money math."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.portfolio.math import (  # noqa: E402
    amount_for,
    cash_after,
    chained_twr,
    concentration,
    derive_holdings,
    validate_sequence,
    weights,
)


def _tx(tx_type: str, **kw) -> dict:
    base = {
        "tx_type": tx_type,
        "symbol": kw.get("symbol", "AAPL"),
        "qty": kw.get("qty"),
        "price_cents": kw.get("price_cents"),
        "fees_cents": kw.get("fees_cents", 0),
        "amount_cents": kw.get("amount_cents", 0),
        "trade_date": kw.get("trade_date", date(2026, 1, 2)),
    }
    return base


def test_average_cost_multiple_buys_with_fees():
    txs = [
        _tx("buy", qty=Decimal("10"), price_cents=10_000, fees_cents=100),  # 10 @ $100 + $1
        _tx("buy", qty=Decimal("10"), price_cents=20_000),  # 10 @ $200
    ]
    h = derive_holdings(txs)["AAPL"]
    # total cost = 10*10000+100 + 10*20000 = 300_100 over 20 sh → 15_005
    assert h["avg_cost_cents"] == 15_005
    assert h["qty"] == Decimal("20")
    assert h["cost_basis_cents"] == 300_100


def test_partial_sell_realized_and_basis():
    txs = [
        _tx("buy", qty=Decimal("10"), price_cents=10_000),
        _tx("sell", qty=Decimal("4"), price_cents=15_000, fees_cents=50),
    ]
    h = derive_holdings(txs)["AAPL"]
    assert h["realized_pnl_cents"] == 4 * 5_000 - 50  # 19_950
    assert h["qty"] == Decimal("6")
    assert h["avg_cost_cents"] == 10_000  # sell never moves avg
    assert h["cost_basis_cents"] == 60_000


def test_sell_all_then_rebuy_resets_basis_keeps_realized():
    txs = [
        _tx("buy", qty=Decimal("5"), price_cents=10_000),
        _tx("sell", qty=Decimal("5"), price_cents=12_000),
        _tx("buy", qty=Decimal("2"), price_cents=30_000, trade_date=date(2026, 2, 2)),
    ]
    h = derive_holdings(txs)["AAPL"]
    assert h["realized_pnl_cents"] == 5 * 2_000
    assert h["avg_cost_cents"] == 30_000  # fresh basis
    assert h["first_acquired"] == date(2026, 2, 2)


def test_oversell_raises():
    txs = [
        _tx("buy", qty=Decimal("3"), price_cents=10_000),
        _tx("sell", qty=Decimal("4"), price_cents=10_000),
    ]
    with pytest.raises(ValueError, match="oversell"):
        derive_holdings(txs)


def test_fractional_shares_exact():
    txs = [_tx("buy", qty=Decimal("0.5"), price_cents=33_333)]
    h = derive_holdings(txs)["AAPL"]
    assert h["cost_basis_cents"] == 16_666  # 0.5*33333 = 16666.5 → banker's round


def test_dividend_and_cash_flow():
    txs = [
        _tx("deposit", symbol=None, amount_cents=100_000),
        _tx("buy", qty=Decimal("5"), price_cents=10_000, amount_cents=-50_000),
        _tx("dividend", amount_cents=1_000),
    ]
    holdings, cash = validate_sequence(txs)
    assert holdings["AAPL"]["cost_basis_cents"] == 50_000  # dividend untouched basis
    assert cash == 51_000


def test_overdraw_raises():
    txs = [
        _tx("deposit", symbol=None, amount_cents=10_000),
        _tx("withdrawal", symbol=None, amount_cents=-20_000),
    ]
    with pytest.raises(ValueError, match="overdraw"):
        cash_after(txs)


def test_amount_for_signs():
    assert amount_for("buy", Decimal("2"), 10_000, 100, 0) == -20_100
    assert amount_for("sell", Decimal("2"), 10_000, 100, 0) == 19_900
    assert amount_for("deposit", None, None, 0, 5_000) == 5_000
    assert amount_for("withdrawal", None, None, 0, 5_000) == -5_000


def test_weights_and_concentration():
    values = {"A": 50_00, "B": 30_00, "C": 20_00}
    w = weights(values)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    conc = concentration(values)
    assert conc["top1_pct"] == 50.0
    assert conc["label"] == "concentrated"  # HHI = .25+.09+.04 = .38
    assert concentration({})["label"] == "empty"


def test_twr_not_distorted_by_deposit():
    # flat market, big deposit mid-way: TWR must be ~0
    series = [
        {"total_value_cents": 100_000, "net_flow_cents": 0},
        {"total_value_cents": 200_000, "net_flow_cents": 100_000},
        {"total_value_cents": 200_000, "net_flow_cents": 0},
    ]
    twr = chained_twr(series)
    assert twr is not None and abs(twr) < 1e-9
    assert chained_twr(series[:1]) is None
