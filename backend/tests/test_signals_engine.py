"""Tests for the SPY signal engine — deterministic label logic + reasons."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.signals.engine import HORIZONS, classify, compute_all  # noqa: E402


def test_horizons_include_one_day():
    assert HORIZONS == [5, 10, 20, 1440]


def test_bullish_on_strong_uptrend():
    prices = [100 + i * 0.1 for i in range(8)]  # monotonic up
    label, conf, reason = classify(prices, 5)
    assert label == "bullish"
    assert 0.0 <= conf <= 1.0
    assert "Up" in reason and reason  # non-empty, explains the move


def test_bearish_on_strong_downtrend():
    label, _, reason = classify([100 - i * 0.1 for i in range(8)], 5)
    assert label == "bearish"
    assert reason


def test_bull_trap_on_failed_breakout():
    label, _, reason = classify([100, 100.5, 101, 101.5, 102, 101.5, 101], 5)
    assert label == "bull_trap"
    assert "failed breakout" in reason


def test_bear_trap_on_failed_breakdown():
    label, _, reason = classify([100, 99.5, 99, 98.5, 98, 98.5, 99], 5)
    assert label == "bear_trap"
    assert "failed breakdown" in reason


def test_neutral_on_flat():
    label, conf, reason = classify([100.0] * 8, 5)
    assert label == "neutral"
    assert conf == 0.0
    assert reason


def test_neutral_on_insufficient_data():
    label, conf, reason = classify([100, 101], 5)
    assert (label, conf) == ("neutral", 0.0)
    assert "history" in reason


def test_one_day_horizon_reason_mentions_a_day():
    _, _, reason = classify([100 + i * 0.1 for i in range(8)], 1440)
    assert "1 day" in reason


def test_threshold_scales_with_horizon():
    prices = [100 + i * 0.002 for i in range(10)]  # ~+0.018% total
    assert classify(prices, 5)[0] in {"bullish", "neutral"}
    assert classify(prices, 20)[0] == "neutral"  # longer horizon needs a bigger move
    assert classify(prices, 1440)[0] == "neutral"  # 1 day needs much more


def test_compute_all_covers_all_horizons_with_reasons():
    prices = [100 + i * 0.1 for i in range(30)]
    out = compute_all(prices)
    assert set(out) == set(HORIZONS)
    for label, conf, reason in out.values():
        assert label in {"bullish", "bearish", "bull_trap", "bear_trap", "neutral"}
        assert 0.0 <= conf <= 1.0
        assert reason
