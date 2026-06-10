"""Tests for the signal retention (daily after-close purge)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.signals.retention import RetentionJob, purge_old  # noqa: E402


@pytest.mark.asyncio
async def test_purge_old_parses_deleted_count():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock(return_value="DELETE 1234")
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    deleted = await purge_old(pool, days=7)
    assert deleted == 1234
    # confirms it filters on a 7-day interval
    assert "make_interval" in conn.execute.await_args.args[0]
    assert conn.execute.await_args.args[1] == 7


@pytest.mark.asyncio
async def test_maybe_purge_waits_until_after_close():
    pool = MagicMock()
    job = RetentionJob(pool)
    now = datetime.now(UTC)
    with (
        patch("app.signals.retention._market_close_passed", return_value=False),
        patch("app.signals.retention.purge_old", AsyncMock(return_value=10)) as purge,
    ):
        result = await job._maybe_purge(now)
    assert result is None
    purge.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_purge_runs_once_per_day_after_close():
    pool = MagicMock()
    job = RetentionJob(pool)
    now = datetime.now(UTC)
    with (
        patch("app.signals.retention._market_close_passed", return_value=True),
        patch("app.signals.retention.purge_old", AsyncMock(return_value=42)) as purge,
    ):
        first = await job._maybe_purge(now)
        second = await job._maybe_purge(now)  # same day → skipped
    assert first == 42
    assert second is None
    purge.assert_awaited_once()
