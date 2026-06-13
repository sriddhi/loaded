"""Tests for the Finnhub earnings-calendar sync + watch seeding."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.fundamentals.calendar import _quarter_end, sync_earnings_calendar  # noqa: E402


def test_quarter_end_mapping():
    assert _quarter_end(1, 2025) == date(2025, 3, 31)
    assert _quarter_end(2, 2025) == date(2025, 6, 30)
    assert _quarter_end(3, 2025) == date(2025, 9, 30)
    assert _quarter_end(4, 2025) == date(2025, 12, 31)
    assert _quarter_end(None, 2025) is None
    assert _quarter_end(2, None) is None


def _mock_http(entries: list[dict]):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"earningsCalendar": entries})
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def _ctx(*a, **k):
        yield client

    return patch("app.fundamentals.calendar.httpx.AsyncClient", _ctx)


@pytest.mark.asyncio
async def test_sync_only_upserts_tracked_symbols():
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[{"symbol": "NVDA"}])  # only NVDA tracked
    conn.execute = AsyncMock()
    entries = [
        {"symbol": "NVDA", "date": "2025-05-28", "hour": "amc", "quarter": 1, "year": 2025},
        {"symbol": "ZZZZ", "date": "2025-05-28", "hour": "bmo", "quarter": 1, "year": 2025},
    ]
    with patch.dict(os.environ, {"FINNHUB_API_KEY": "k"}), _mock_http(entries):
        written = await sync_earnings_calendar(conn)
    assert written == 1  # ZZZZ skipped (untracked)
    assert conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_sync_skipped_without_key():
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[{"symbol": "NVDA"}])
    with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}):
        written = await sync_earnings_calendar(conn)
    assert written == 0
