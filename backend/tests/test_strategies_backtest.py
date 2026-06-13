"""Tests for the strategy backtest-run framework (persist + multi-period + error)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.strategies import backtest  # noqa: E402
from app.strategies.models import EvalResult, StrategyConfig  # noqa: E402

_CONFIG = StrategyConfig(
    name="x", description="x", type="CUSTOM", parameters={}, filters={}, signal_logic="x"
)
_STRATEGY = {"id": 5, "config": _CONFIG.model_dump(), "symbols": ["SPY"], "run_config": {}}


def _pool():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchval = AsyncMock(return_value=42)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool, conn


def _eval_result():
    return EvalResult(
        strategy_name="x",
        symbol="SPY",
        period="1y",
        total_return_pct=12.5,
        sharpe_ratio=1.1,
        max_drawdown_pct=-8.0,
        win_rate=0.6,
        total_trades=10,
        equity_curve=[10000.0, 11250.0],
        signals=[],
    )


@pytest.mark.asyncio
async def test_run_backtest_for_persists_ok_run():
    pool, conn = _pool()
    with patch("app.strategies.backtest.evaluate_strategy", return_value=_eval_result()):
        out = await backtest.run_backtest_for(pool, _STRATEGY, "1y")
    assert out["status"] == "ok"
    assert out["metrics"]["total_return_pct"] == 12.5
    assert out["run_id"] == 42
    conn.fetchval.assert_awaited()  # inserted a strategy_runs row


@pytest.mark.asyncio
async def test_run_backtest_for_records_error_run():
    pool, conn = _pool()
    with patch("app.strategies.backtest.evaluate_strategy", side_effect=ValueError("no data")):
        out = await backtest.run_backtest_for(pool, _STRATEGY, "1y")
    assert out["status"] == "error"
    assert "no data" in out["detail"]
    conn.fetchval.assert_awaited()  # an error run row still written


@pytest.mark.asyncio
async def test_run_backtests_loops_periods():
    pool, _ = _pool()
    with patch(
        "app.strategies.backtest.run_backtest_for",
        AsyncMock(side_effect=lambda *a, **k: {"period": a[2], "status": "ok"}),
    ):
        out = await backtest.run_backtests(pool, _STRATEGY, ["1y", "6mo", "3mo"])
    assert [r["period"] for r in out] == ["1y", "6mo", "3mo"]
