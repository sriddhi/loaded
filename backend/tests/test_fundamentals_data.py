"""Tests for the raw-statement fetcher (yfinance mocked)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from app.fundamentals.data import _to_int, fetch_raw_statements  # noqa: E402


def test_to_int_handles_none_and_nan():
    assert _to_int(None) is None
    assert _to_int(float("nan")) is None
    assert _to_int(1000.0) == 1000
    assert _to_int("x") is None


def _fake_ticker() -> MagicMock:
    col = pd.Timestamp("2024-12-31")
    fin = pd.DataFrame({col: {"Total Revenue": 1000.0, "Net Income": 100.0, "Diluted EPS": 5.0}})
    bs = pd.DataFrame({col: {"Total Assets": 2000.0, "Stockholders Equity": 500.0}})
    cf = pd.DataFrame({col: {"Operating Cash Flow": 300.0, "Capital Expenditure": -50.0}})
    empty = pd.DataFrame()
    t = MagicMock()
    t.info = {
        "symbol": "NVDA",
        "longName": "NVIDIA",
        "sharesOutstanding": 1000,
        "currency": "USD",
        "sector": "Technology",
        "industry": "Semiconductors",
        "exchange": "NMS",
    }
    t.financials = fin
    t.quarterly_financials = empty
    t.balance_sheet = bs
    t.quarterly_balance_sheet = empty
    t.cashflow = cf
    t.quarterly_cashflow = empty
    return t


@pytest.mark.asyncio
async def test_fetch_raw_statements_shapes_cents():
    with patch("app.fundamentals.data.yf.Ticker", return_value=_fake_ticker()):
        data = await fetch_raw_statements("NVDA")
    assert data["equity"]["symbol"] == "NVDA"
    assert data["equity"]["currency"] == "USD"
    annual = data["annual"]
    assert len(annual) == 1
    p = annual[0]
    assert p["revenue"] == 1000_00  # dollars → cents
    assert p["net_income"] == 100_00
    assert p["eps_diluted"] == 5.0
    assert p["shares_outstanding"] == 1000
    assert p["free_cash_flow"] == (300_00 + -50_00)  # OCF + capex (capex negative)


@pytest.mark.asyncio
async def test_unknown_symbol_raises():
    t = MagicMock()
    t.info = {}
    with patch("app.fundamentals.data.yf.Ticker", return_value=t):  # noqa: SIM117
        with pytest.raises(ValueError):
            await fetch_raw_statements("ZZZZ")
