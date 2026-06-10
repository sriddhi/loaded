"""Tests for the fundamentals scheduler (window parsing + daily-sync gating)."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.fundamentals.scheduler import FundamentalsScheduler, _in_window, _window  # noqa: E402

_ET = ZoneInfo("America/New_York")


def test_window_default_and_custom():
    with patch.dict(os.environ, {"EARNINGS_POLL_WINDOW": ""}):
        assert _window() == (time(6, 0), time(22, 0))  # malformed/empty → default
    with patch.dict(os.environ, {"EARNINGS_POLL_WINDOW": "08:30-17:15"}):
        assert _window() == (time(8, 30), time(17, 15))


def test_in_window():
    with patch.dict(os.environ, {"EARNINGS_POLL_WINDOW": "06:00-22:00"}):
        assert _in_window(datetime(2024, 7, 8, 12, 0, tzinfo=_ET)) is True
        assert _in_window(datetime(2024, 7, 8, 3, 0, tzinfo=_ET)) is False
        assert _in_window(datetime(2024, 7, 8, 23, 0, tzinfo=_ET)) is False


@pytest.mark.asyncio
async def test_daily_sync_runs_once_per_day():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    sched = FundamentalsScheduler(pool)
    with (
        patch(
            "app.fundamentals.scheduler.sync_earnings_calendar", AsyncMock(return_value=3)
        ) as sync,
        patch("app.fundamentals.scheduler.seed_watch", AsyncMock(return_value=1)),
    ):
        await sched._daily_calendar_sync(date(2024, 7, 8))
        await sched._daily_calendar_sync(date(2024, 7, 8))  # same day → skip
    sync.assert_awaited_once()
