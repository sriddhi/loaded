"""Tests for the signal backtester — thesis judgment + due-evaluation + summary."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.signals.backtest import accuracy_summary, evaluate_due, judge  # noqa: E402


def test_judge_bullish_correct_when_price_rises():
    assert judge("bullish", 100.0, 101.0, 5) == "correct"
    assert judge("bullish", 100.0, 99.0, 5) == "wrong"


def test_judge_bearish_correct_when_price_falls():
    assert judge("bearish", 100.0, 99.0, 5) == "correct"
    assert judge("bearish", 100.0, 101.0, 5) == "wrong"


def test_judge_traps_expect_reversal():
    # bull_trap → failed breakout → expect downside
    assert judge("bull_trap", 100.0, 98.0, 5) == "correct"
    assert judge("bull_trap", 100.0, 102.0, 5) == "wrong"
    # bear_trap → failed breakdown → expect upside
    assert judge("bear_trap", 100.0, 102.0, 5) == "correct"
    assert judge("bear_trap", 100.0, 98.0, 5) == "wrong"


def test_judge_neutral_correct_when_flat_within_band():
    # 5m threshold ≈ 0.11%; a tiny move stays "correct" (flat), a big move is "wrong".
    assert judge("neutral", 100.0, 100.05, 5) == "correct"
    assert judge("neutral", 100.0, 105.0, 5) == "wrong"


@pytest.mark.asyncio
async def test_evaluate_due_resolves_and_updates():
    now = datetime.now(UTC)
    due_row = {
        "id": 7,
        "symbol": "SPY",
        "ts": now - timedelta(minutes=10),
        "price": 100.0,
        "label": "bullish",
    }
    fut_row = {"price": 101.5}  # rose → bullish correct

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    # Horizons are [1, 5, 10, 20, 1440]; the 5m pass returns the due row.
    conn.fetch = AsyncMock(side_effect=[[], [due_row], [], [], []])
    conn.fetchrow = AsyncMock(return_value=fut_row)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    resolved = await evaluate_due(pool)
    assert resolved == 1
    args = conn.execute.await_args.args
    assert args[0].startswith("UPDATE spy_signals SET res_5m")
    assert args[1] == "correct"  # outcome
    assert args[2] == 7  # id


@pytest.mark.asyncio
async def test_evaluate_due_skips_when_no_future_price():
    now = datetime.now(UTC)
    due_row = {
        "id": 1,
        "symbol": "MU",
        "ts": now - timedelta(minutes=30),
        "price": 100.0,
        "label": "bearish",
    }
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetch = AsyncMock(side_effect=[[], [due_row], [], [], []])
    conn.fetchrow = AsyncMock(return_value=None)  # no realized price yet
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    resolved = await evaluate_due(pool)
    assert resolved == 0
    conn.execute.assert_not_awaited()


def test_accuracy_summary_counts_only_resolved():
    rows = [
        {
            "signals": [
                {"horizon_min": 5, "outcome": "correct"},
                {"horizon_min": 10, "outcome": "wrong"},
                {"horizon_min": 20, "outcome": "pending"},
            ]
        },
        {
            "signals": [
                {"horizon_min": 5, "outcome": "correct"},
                {"horizon_min": 10, "outcome": "correct"},
            ]
        },
    ]
    acc = accuracy_summary(rows)
    assert acc[5] == {"hits": 2, "total": 2}
    assert acc[10] == {"hits": 1, "total": 2}
    assert acc[20] == {"hits": 0, "total": 0}  # all pending → not counted
