"""Tests for lazy-TTL freshness + the earnings poller."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.fundamentals import refresh  # noqa: E402


def _pool_with_conn(conn: MagicMock) -> MagicMock:
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool


# ── ensure_fresh ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_fresh_cold_blocks_and_fetches():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)  # no rows
    pool = _pool_with_conn(conn)
    with patch("app.fundamentals.refresh.ingest_statements", AsyncMock()) as ing:
        await refresh.ensure_fresh(pool, "NVDA", tracked=True)
    ing.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_fresh_fresh_does_nothing():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=datetime.now(UTC))  # just fetched
    pool = _pool_with_conn(conn)
    with (
        patch("app.fundamentals.refresh.ingest_statements", AsyncMock()) as ing,
        patch("app.fundamentals.refresh._schedule_bg_refresh") as sched,
    ):
        await refresh.ensure_fresh(pool, "NVDA", tracked=True)
    ing.assert_not_awaited()
    sched.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_fresh_stale_schedules_background():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=datetime.now(UTC) - timedelta(days=40))
    pool = _pool_with_conn(conn)
    with patch("app.fundamentals.refresh._schedule_bg_refresh") as sched:
        await refresh.ensure_fresh(pool, "NVDA", tracked=True)  # tracked TTL 30d → stale
    sched.assert_called_once()


# ── poll_earnings_watch ───────────────────────────────────────────────────────


def _poll_conn(pending_rows: list[dict], max_period_end: date | None) -> MagicMock:
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetch = AsyncMock(return_value=pending_rows)
    conn.fetchval = AsyncMock(return_value=max_period_end)
    conn.execute = AsyncMock()
    return conn


def _last_status(conn: MagicMock) -> str:
    # Inspect the UPDATE SQL passed to execute.
    sql = conn.execute.await_args.args[0]
    if "status='done'" in sql:
        return "done"
    if "status='aged_out'" in sql:
        return "aged_out"
    return "pending"


@pytest.mark.asyncio
async def test_poll_marks_done_when_period_advanced():
    row = {
        "id": 1,
        "symbol": "NVDA",
        "earnings_date": date.today(),
        "expected_period_end": date(2025, 3, 31),
    }
    conn = _poll_conn([row], max_period_end=date(2025, 3, 31))  # new quarter present
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    with patch("app.fundamentals.refresh.ingest_statements", AsyncMock()):
        counts = await refresh.poll_earnings_watch(pool)
    assert counts["done"] == 1
    assert _last_status(conn) == "done"


@pytest.mark.asyncio
async def test_poll_stays_pending_when_not_yet_available():
    # earnings today, new quarter not yet in yfinance → still pending (not aged out)
    row = {
        "id": 1,
        "symbol": "NVDA",
        "earnings_date": date.today(),
        "expected_period_end": date(2025, 6, 30),
    }
    conn = _poll_conn([row], max_period_end=date(2025, 3, 31))  # still old quarter
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    with patch("app.fundamentals.refresh.ingest_statements", AsyncMock()):
        counts = await refresh.poll_earnings_watch(pool)
    assert counts["pending"] == 1
    assert _last_status(conn) == "pending"


@pytest.mark.asyncio
async def test_poll_ages_out_after_window():
    old_earnings = date.today() - timedelta(days=10)  # well past T+2 trading days
    row = {
        "id": 1,
        "symbol": "NVDA",
        "earnings_date": old_earnings,
        "expected_period_end": date(2025, 6, 30),
    }
    conn = _poll_conn([row], max_period_end=date(2025, 3, 31))  # never advanced
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    with patch("app.fundamentals.refresh.ingest_statements", AsyncMock()):
        counts = await refresh.poll_earnings_watch(pool)
    assert counts["aged_out"] == 1
    assert _last_status(conn) == "aged_out"
