"""Tests for the SPY signal job: quote fetch, tick, query helpers."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.signals import job  # noqa: E402


def test_signals_enabled_follows_env():
    with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}):
        assert job.signals_enabled() is False
    with patch.dict(os.environ, {"FINNHUB_API_KEY": "k"}):
        assert job.signals_enabled() is True


def _mock_http(payload: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload)
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def _ctx(*a, **k):
        yield client

    return patch("app.signals.job.httpx.AsyncClient", _ctx)


@pytest.mark.asyncio
async def test_fetch_spy_quote_parses_price():
    with patch.dict(os.environ, {"FINNHUB_API_KEY": "k"}), _mock_http({"c": 512.34}):
        assert await job.fetch_spy_quote() == 512.34


@pytest.mark.asyncio
async def test_fetch_spy_quote_none_without_key():
    with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}):
        assert await job.fetch_spy_quote() is None


@pytest.mark.asyncio
async def test_fetch_spy_quote_none_on_zero_price():
    with patch.dict(os.environ, {"FINNHUB_API_KEY": "k"}), _mock_http({"c": 0}):
        assert await job.fetch_spy_quote() is None


@pytest.mark.asyncio
async def test_tick_once_skips_without_price():
    pool = MagicMock()
    with patch("app.signals.job.fetch_spy_quote", AsyncMock(return_value=None)):
        assert await job.tick_once(pool) is None


@pytest.mark.asyncio
async def test_tick_once_stores_and_returns_signal():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetch = AsyncMock(return_value=[{"price": 100 + i} for i in range(6)])
    conn.fetchval = AsyncMock(return_value=datetime.now(UTC))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    with patch("app.signals.job.fetch_spy_quote", AsyncMock(return_value=108.0)):
        result = await job.tick_once(pool)
    assert result is not None
    assert result["price"] == 108.0
    assert {s["horizon_min"] for s in result["signals"]} == {5, 10, 20, 1440}
    assert all(s["reason"] for s in result["signals"])  # every rating has a reason
    conn.fetchval.assert_awaited_once()  # inserted a row
