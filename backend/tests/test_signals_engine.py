"""Tests for the signal engine — deterministic label logic + reasons + volume."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.signals.engine import HORIZONS, classify, compute_all  # noqa: E402


def _flat_vol(n: int, v: float = 1000.0) -> list[float]:
    return [v] * n


def test_horizons_include_one_minute_and_one_day():
    assert HORIZONS == [1, 5, 10, 20, 1440]


def test_bullish_on_strong_uptrend():
    prices = [100 + i * 0.1 for i in range(8)]  # monotonic up
    label, conf, reason = classify(prices, _flat_vol(8), 5)
    assert label == "bullish"
    assert 0.0 <= conf <= 1.0
    assert "Up" in reason and reason  # non-empty, explains the move


def test_bearish_on_strong_downtrend():
    label, _, reason = classify([100 - i * 0.1 for i in range(8)], _flat_vol(8), 5)
    assert label == "bearish"
    assert reason


def test_bull_trap_on_failed_breakout():
    label, _, reason = classify([100, 100.5, 101, 101.5, 102, 101.5, 101], _flat_vol(7), 5)
    assert label == "bull_trap"
    assert "failed breakout" in reason


def test_bear_trap_on_failed_breakdown():
    label, _, reason = classify([100, 99.5, 99, 98.5, 98, 98.5, 99], _flat_vol(7), 5)
    assert label == "bear_trap"
    assert "failed breakdown" in reason


def test_neutral_on_flat():
    label, conf, reason = classify([100.0] * 8, _flat_vol(8), 5)
    assert label == "neutral"
    assert conf == 0.0
    assert reason


def test_neutral_on_insufficient_data():
    label, conf, reason = classify([100, 101], None, 5)
    assert (label, conf) == ("neutral", 0.0)
    assert "history" in reason


def test_one_day_horizon_reason_mentions_a_day():
    _, _, reason = classify([100 + i * 0.1 for i in range(8)], _flat_vol(8), 1440)
    assert "1 day" in reason


def test_threshold_scales_with_horizon():
    prices = [100 + i * 0.002 for i in range(10)]  # ~+0.018% total
    assert classify(prices, _flat_vol(10), 5)[0] in {"bullish", "neutral"}
    assert classify(prices, _flat_vol(10), 20)[0] == "neutral"  # longer horizon needs a bigger move
    assert classify(prices, _flat_vol(10), 1440)[0] == "neutral"  # 1 day needs much more


def test_volume_mentioned_in_reason_when_provided():
    prices = [100 + i * 0.1 for i in range(8)]
    _, _, reason = classify(prices, _flat_vol(8), 5)
    assert "volume" in reason.lower()


def test_breakout_on_light_volume_is_a_bull_trap():
    # Strong uptrend, but volume collapses on the latest bars → unconfirmed move.
    prices = [100 + i * 0.1 for i in range(8)]
    volumes = [1000, 1000, 1000, 1000, 1000, 1000, 100, 80]
    label, _, reason = classify(prices, volumes, 5)
    assert label == "bull_trap"
    assert "unconfirmed breakout" in reason


def test_breakdown_on_light_volume_is_a_bear_trap():
    prices = [100 - i * 0.1 for i in range(8)]
    volumes = [1000, 1000, 1000, 1000, 1000, 1000, 100, 80]
    label, _, reason = classify(prices, volumes, 5)
    assert label == "bear_trap"
    assert "unconfirmed breakdown" in reason


def test_heavy_volume_boosts_confidence_over_light():
    prices = [100 + i * 0.1 for i in range(8)]
    heavy = [1000, 1000, 1000, 1000, 1000, 1000, 3000, 3000]
    light = [1000, 1000, 1000, 1000, 1000, 1000, 800, 800]
    _, conf_heavy, _ = classify(prices, heavy, 5)
    _, conf_light, _ = classify(prices, light, 5)
    assert conf_heavy > conf_light


def test_compute_all_covers_all_horizons_with_reasons():
    prices = [100 + i * 0.1 for i in range(30)]
    out = compute_all(prices, _flat_vol(30))
    assert set(out) == set(HORIZONS)
    for label, conf, reason in out.values():
        assert label in {"bullish", "bearish", "bull_trap", "bear_trap", "neutral"}
        assert 0.0 <= conf <= 1.0
        assert reason
