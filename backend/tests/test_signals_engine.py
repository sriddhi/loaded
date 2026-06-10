"""Tests for the SPY signal engine — deterministic label logic."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.signals.engine import HORIZONS, classify, compute_all  # noqa: E402


def test_bullish_on_strong_uptrend():
    prices = [100 + i * 0.1 for i in range(8)]  # monotonic up
    label, conf = classify(prices, 5)
    assert label == "bullish"
    assert 0.0 <= conf <= 1.0


def test_bearish_on_strong_downtrend():
    prices = [100 - i * 0.1 for i in range(8)]
    label, _ = classify(prices, 5)
    assert label == "bearish"


def test_bull_trap_on_failed_breakout():
    # rises to a recent high (102) then reverses down
    prices = [100, 100.5, 101, 101.5, 102, 101.5, 101]
    label, _ = classify(prices, 5)
    assert label == "bull_trap"


def test_bear_trap_on_failed_breakdown():
    # drops to a recent low (98) then rallies up
    prices = [100, 99.5, 99, 98.5, 98, 98.5, 99]
    label, _ = classify(prices, 5)
    assert label == "bear_trap"


def test_neutral_on_flat():
    prices = [100.0] * 8
    label, conf = classify(prices, 5)
    assert label == "neutral"
    assert conf == 0.0


def test_neutral_on_insufficient_data():
    assert classify([100, 101], 5) == ("neutral", 0.0)


def test_threshold_scales_with_horizon():
    # a small move that's "bullish" at 5m may be "neutral" at 20m (bigger bar needed)
    prices = [100 + i * 0.002 for i in range(10)]  # ~+0.018% total
    short = classify(prices, 5)[0]
    long = classify(prices, 20)[0]
    assert short in {"bullish", "neutral"}
    assert long == "neutral"  # longer horizon needs a bigger move


def test_compute_all_covers_horizons():
    prices = [100 + i * 0.1 for i in range(20)]
    out = compute_all(prices)
    assert set(out) == set(HORIZONS)
    for label, conf in out.values():
        assert label in {"bullish", "bearish", "bull_trap", "bear_trap", "neutral"}
        assert 0.0 <= conf <= 1.0
