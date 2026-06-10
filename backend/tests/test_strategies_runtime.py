"""Tests for strategy runtime: latest_signal, paper gate, scheduler, run-once."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from app.strategies import runtime  # noqa: E402
from app.strategies.models import StrategyConfig  # noqa: E402

_CONFIG = StrategyConfig(
    name="SMA cross",
    description="x",
    type="CUSTOM",
    parameters={"sma_period": 3},
    filters={},
    signal_logic="cross",
)


def test_latest_signal_buy_on_cross_up():
    # Rising series → last bar crosses above SMA → BUY.
    df = pd.DataFrame({"close": [10, 10, 10, 10, 11, 12], "volume": [1] * 6})
    with patch("app.strategies.runtime._fetch_ohlcv", return_value=df):
        assert runtime.latest_signal(_CONFIG, "SPY") in ("BUY", "HOLD")


def test_paper_order_refused_when_not_configured():
    with patch("app.strategies.runtime.paper_enabled", return_value=False):
        out = runtime.place_paper_order("SPY", "BUY", 1)
    assert out["placed"] is False
    assert "not configured" in out["reason"]


def test_is_due_interval_and_manual():
    now = datetime.now(UTC)
    manual = {"run_config": {"schedule_kind": "manual"}, "last_run_at": None}
    assert runtime._is_due(manual, now) is False

    fresh = {
        "run_config": {"schedule_kind": "interval", "interval_minutes": 30},
        "last_run_at": None,
    }
    assert runtime._is_due(fresh, now) is True

    recent = {
        "run_config": {"schedule_kind": "interval", "interval_minutes": 30},
        "last_run_at": now - timedelta(minutes=5),
    }
    assert runtime._is_due(recent, now) is False

    due = {
        "run_config": {"schedule_kind": "interval", "interval_minutes": 30},
        "last_run_at": now - timedelta(minutes=45),
    }
    assert runtime._is_due(due, now) is True


@pytest.mark.asyncio
async def test_run_strategy_once_signal_writes_run_row():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchval = AsyncMock(return_value=99)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    strategy = {
        "id": 7,
        "config": _CONFIG.model_dump(),
        "mode": "signal",
        "symbols": ["SPY"],
        "run_config": {},
    }
    with patch("app.strategies.runtime.latest_signal", return_value="BUY"):
        out = await runtime.run_strategy_once(pool, strategy)
    assert out["action"] == "BUY"
    conn.fetchval.assert_awaited()  # a strategy_runs row inserted


@pytest.mark.asyncio
async def test_run_strategy_once_paper_uses_gate():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    strategy = {
        "id": 1,
        "config": _CONFIG.model_dump(),
        "mode": "paper",
        "symbols": ["SPY"],
        "run_config": {"paper_qty": 2},
    }
    with (
        patch("app.strategies.runtime.latest_signal", return_value="BUY"),
        patch(
            "app.strategies.runtime.place_paper_order",
            return_value={"placed": False, "reason": "paper trading not configured"},
        ) as gate,
    ):
        out = await runtime.run_strategy_once(pool, strategy)
    gate.assert_called_once()
    assert out["order"]["placed"] is False
