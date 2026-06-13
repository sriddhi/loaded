"""Scheduler gating, lock exclusivity and phase fault isolation."""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.screener.job import SCREENER_LOCK, ScreenerScheduler, run_screener  # noqa: E402

ET = ZoneInfo("America/New_York")


def test_due_gating():
    sched = ScreenerScheduler(MagicMock())
    assert sched._due(datetime(2026, 6, 12, 16, 30, tzinfo=ET)) is True  # Fri after close
    assert sched._due(datetime(2026, 6, 12, 15, 0, tzinfo=ET)) is False  # market hours
    assert sched._due(datetime(2026, 6, 13, 18, 0, tzinfo=ET)) is False  # Saturday
    assert sched._due(datetime(2026, 6, 12, 16, 10, tzinfo=ET)) is True  # boundary


@pytest.mark.asyncio
async def test_lock_blocks_concurrent_runs():
    assert not SCREENER_LOCK.locked()
    async with SCREENER_LOCK:
        assert SCREENER_LOCK.locked()  # endpoint checks this and 409s


@pytest.mark.asyncio
async def test_phases_fault_isolated():
    """Universe + ingest + closes all fail → scoring still runs on cached data."""
    pool = MagicMock()
    members = [{"symbol": "AAA", "sector": "Energy", "equity_id": 1}]
    with (
        patch("app.screener.job.refresh_universe", AsyncMock(side_effect=RuntimeError("net"))),
        patch("app.screener.job.universe_symbols", AsyncMock(return_value=members)),
        patch("app.screener.job._ingest_stale", AsyncMock(side_effect=RuntimeError("yf down"))),
        patch("app.screener.job.refresh_closes", AsyncMock(side_effect=RuntimeError("yf down"))),
        patch("app.screener.job._load_inputs", AsyncMock(return_value=[{"symbol": "AAA"}])),
        patch("app.screener.job._persist_scores", AsyncMock(return_value=1)) as persist,
    ):
        summary = await run_screener(pool)
    assert summary["scored"] == 1
    persist.assert_awaited_once()
