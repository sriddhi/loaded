"""Tests for refresh staleness + upsert flow (mocked FRED + pool)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.macro import refresh as r  # noqa: E402


def test_ttl_by_frequency():
    assert r.ttl_hours("DGS2") == 6  # daily
    assert r.ttl_hours("ICSA") == 12  # weekly
    assert r.ttl_hours("CPIAUCSL") == 24  # monthly
    assert r.ttl_hours("UNKNOWN") == 24  # default


@pytest.mark.asyncio
async def test_series_stale_logic():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)
    assert await r.series_stale(conn, "DGS2") is True  # never fetched
    conn.fetchval = AsyncMock(return_value=datetime.now(UTC) - timedelta(hours=1))
    assert await r.series_stale(conn, "DGS2") is False  # fresh (6h TTL)
    conn.fetchval = AsyncMock(return_value=datetime.now(UTC) - timedelta(hours=7))
    assert await r.series_stale(conn, "DGS2") is True  # past TTL


def _pool_with_conn():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool, conn


@pytest.mark.asyncio
async def test_refresh_series_upserts_observations():
    pool, conn = _pool_with_conn()
    obs = [(date(2026, 1, 1), 3.1), (date(2026, 2, 1), 3.2)]
    with (
        patch("app.macro.refresh.fetch_observations", AsyncMock(return_value=obs)),
        patch("app.macro.refresh.fetch_meta", AsyncMock(return_value={})),
    ):
        n = await r.refresh_series(pool, "CPIAUCSL")
    assert n == 2
    # 1 series upsert via execute + 1 bulk observation upsert via executemany
    assert conn.execute.await_count == 1
    conn.executemany.assert_awaited_once()
    assert len(conn.executemany.await_args.args[1]) == 2


@pytest.mark.asyncio
async def test_refresh_stale_swallows_per_series_errors():
    pool, _ = _pool_with_conn()
    with (
        patch("app.macro.refresh.series_stale", AsyncMock(return_value=True)),
        patch("app.macro.refresh.refresh_series", AsyncMock(side_effect=RuntimeError("net down"))),
    ):
        out = await r.refresh_stale(pool)
    assert out == {}  # all failed, none raised
