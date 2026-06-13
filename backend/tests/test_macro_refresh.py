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


@pytest.mark.asyncio
async def test_update_alert_states_records_since():
    pool, conn = _pool_with_conn()
    since = datetime(2026, 6, 1, tzinfo=UTC)
    conn.fetchrow = AsyncMock(return_value={"fired": True, "since": since})
    alerts = [{"id": "margin_squeeze", "fired": True}]
    out = await r.update_alert_states(pool, alerts)
    assert out["margin_squeeze"]["since"] == since.isoformat()
    sql = conn.fetchrow.await_args.args[0]
    assert "IS DISTINCT FROM" in sql  # `since` only resets on a state transition


@pytest.mark.asyncio
async def test_evaluate_now_stamps_timing_and_explainers():
    pool, _ = _pool_with_conn()
    data = {
        "DGS2": [{"date": "2026-06-10", "value": 3.0}],  # < 3.5 → fires
    }
    states = {"two_year_below_3_5": {"since": "2026-06-01T00:00:00+00:00"}}
    with patch("app.macro.refresh.update_alert_states", AsyncMock(return_value=states)):
        alerts = await r.evaluate_now(pool, data, include_technicals=False)
    a = next(x for x in alerts if x["id"] == "two_year_below_3_5")
    assert a["fired"] is True
    assert a["fired_since"] == "2026-06-01T00:00:00+00:00"
    assert a["as_of"] == "2026-06-10"
    assert a["meaning"] and a["impact"]
    # not-fired alerts carry no fired_since but still get explainers
    b = next(x for x in alerts if x["id"] == "margin_squeeze")
    assert b["fired_since"] is None and b["meaning"]
