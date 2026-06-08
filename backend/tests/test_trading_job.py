"""Tests for trading job lifecycle and API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.trading.state import reset_state, trading_state

# ── Helpers ───────────────────────────────────────────────────────────────────


def _reset():
    reset_state()


# ── Job lifecycle ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_start_sets_status():
    _reset()
    from app.trading.job import trading_job

    # Patch _loop so it doesn't actually run
    with patch.object(trading_job, "_loop", new_callable=AsyncMock):
        await trading_job.start()
        assert trading_state.status in ("capturing_orb", "trading")
        await trading_job.stop()


@pytest.mark.asyncio
async def test_job_start_idempotent():
    _reset()
    from app.trading.job import trading_job

    with patch.object(trading_job, "_loop", new_callable=AsyncMock):
        await trading_job.start()
        task1 = trading_job._task
        await trading_job.start()  # second call — should be no-op
        task2 = trading_job._task
        assert task1 is task2
        await trading_job.stop()


@pytest.mark.asyncio
async def test_job_stop_sets_status_stopped():
    _reset()
    from app.trading.job import trading_job

    with patch.object(trading_job, "_loop", new_callable=AsyncMock):
        await trading_job.start()
        await trading_job.stop()
        assert trading_state.status == "stopped"


# ── Tick behavior ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_outside_market_hours_no_entry():
    """_tick during off-hours does nothing."""
    _reset()
    from datetime import datetime, timedelta, timezone

    et = timezone(timedelta(hours=-4))
    fake_now = datetime(2024, 6, 7, 8, 0, tzinfo=et)  # 8 AM ET = before open

    from app.trading.job import TradingJob

    job = TradingJob()
    with (
        patch("app.trading.job._now_et", return_value=fake_now),
        patch.object(job, "_fetch_spy_price", new_callable=AsyncMock, return_value=530.0),
        patch.object(job, "_place_entry", new_callable=AsyncMock) as mock_entry,
    ):
        await job._tick()
        mock_entry.assert_not_called()


@pytest.mark.asyncio
async def test_tick_during_orb_window_no_entry():
    """_tick at 9:45 ET should update ORB but not enter trades."""
    _reset()
    from datetime import datetime, timedelta, timezone

    et = timezone(timedelta(hours=-4))
    fake_now = datetime(2024, 6, 7, 9, 45, tzinfo=et)

    from app.trading.job import TradingJob

    job = TradingJob()
    with (
        patch("app.trading.job._now_et", return_value=fake_now),
        patch.object(job, "_fetch_spy_price", new_callable=AsyncMock, return_value=530.0),
        patch.object(job, "_update_orb", new_callable=AsyncMock) as mock_orb,
        patch.object(job, "_place_entry", new_callable=AsyncMock) as mock_entry,
    ):
        await job._tick()
        mock_orb.assert_called_once()
        mock_entry.assert_not_called()


# ── API endpoints ─────────────────────────────────────────────────────────────


from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def test_api_status_endpoint_unauthorized():
    from app.auth.security import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/trading/status")
    assert resp.status_code == 401
    app.dependency_overrides.clear()


def test_api_start_endpoint_unauthorized():
    from app.auth.security import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/trading/start")
    assert resp.status_code == 401
    app.dependency_overrides.clear()


def test_api_status_returns_schema():
    """With auth bypassed, GET /trading/status returns all required fields."""
    from app.auth.security import get_current_user

    fake_user = MagicMock()
    fake_user.id = 1
    app.dependency_overrides[get_current_user] = lambda: fake_user
    _reset()

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/trading/status")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("status", "open_positions", "entry_counts", "daily_pnl_usd", "recent_errors"):
        assert field in body, f"missing field: {field}"
    app.dependency_overrides.clear()


def test_api_reset_sets_idle():
    from app.auth.security import get_current_user

    fake_user = MagicMock()
    fake_user.id = 1
    app.dependency_overrides[get_current_user] = lambda: fake_user

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/trading/reset")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"
    app.dependency_overrides.clear()
