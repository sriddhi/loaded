"""Tests for the NYSE trading-calendar helpers (real holidays, not weekday math)."""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.fundamentals.market_calendar import (  # noqa: E402
    add_trading_days,
    is_trading_day,
    trading_days_between,
)


def test_weekend_is_not_a_trading_day():
    assert is_trading_day(date(2024, 7, 6)) is False  # Saturday


def test_july_4_holiday_is_not_a_trading_day():
    assert is_trading_day(date(2024, 7, 4)) is False  # Independence Day


def test_normal_weekday_is_a_trading_day():
    assert is_trading_day(date(2024, 7, 8)) is True  # Monday


def test_add_trading_days_skips_holiday():
    # From Wed 2024-07-03, +2 trading days must skip Thu Jul 4 (holiday) AND the
    # weekend → lands Mon Jul 8, which is LATER than naive weekday math (Jul 5).
    assert add_trading_days(date(2024, 7, 3), 2) == date(2024, 7, 8)


def test_add_trading_days_over_weekend():
    # Friday +1 trading day → Monday
    assert add_trading_days(date(2024, 7, 5), 1) == date(2024, 7, 8)


def test_trading_days_between_excludes_holiday():
    # Wed Jul 3 → Mon Jul 8: trading sessions strictly after Jul 3 are Jul 5, Jul 8 = 2
    assert trading_days_between(date(2024, 7, 3), date(2024, 7, 8)) == 2


def test_trading_days_between_zero_when_end_not_after_start():
    assert trading_days_between(date(2024, 7, 8), date(2024, 7, 8)) == 0
