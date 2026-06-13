"""Tests for the fundamentals OOP models + registry."""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pydantic  # noqa: E402
from app.fundamentals.models import (  # noqa: E402
    BaseFinancials,
    EquityFinancials,
    build_financials,
    register_financials,
)


def test_equity_is_registered_default():
    f = build_financials("us_equity", symbol="X", period_type="annual", period_end=date(2024, 1, 1))
    assert isinstance(f, EquityFinancials)


def test_unknown_asset_class_falls_back_to_equity():
    f = build_financials("weird", symbol="X", period_type="annual", period_end=date(2024, 1, 1))
    assert isinstance(f, EquityFinancials)
    assert f.asset_class == "weird"


def test_gross_margin_computed_field():
    f = EquityFinancials(
        symbol="X",
        period_type="annual",
        period_end=date(2024, 1, 1),
        revenue=100_00,
        gross_profit=40_00,
    )
    assert f.gross_margin == 0.4


def test_models_are_frozen():
    f = EquityFinancials(symbol="X", period_type="annual", period_end=date(2024, 1, 1))
    try:
        f.revenue = 1  # type: ignore[misc]
        raise AssertionError("frozen model should reject mutation")
    except pydantic.ValidationError:
        pass


def test_custom_subclass_plugs_in_without_union_edit():
    class EtfFinancials(EquityFinancials):
        asset_class_key = "us_etf"
        expense_ratio: float | None = None

    register_financials(EtfFinancials)
    f = build_financials("us_etf", symbol="SPY", period_type="annual", period_end=date(2024, 1, 1))
    assert isinstance(f, EtfFinancials)
    assert isinstance(f, BaseFinancials)
