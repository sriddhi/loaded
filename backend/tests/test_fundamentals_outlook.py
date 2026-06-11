"""Tests for the deterministic outlook (fair value, horizons, tags)."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.fundamentals import outlook  # noqa: E402


def test_fair_value_scales_with_growth_and_caps():
    low_g = outlook.compute_fair_value(5.0, 0.0)
    high_g = outlook.compute_fair_value(5.0, 0.30)
    assert low_g is not None and high_g is not None
    assert low_g["multiple"] == 15.0  # baseline
    assert high_g["multiple"] == 40.0  # 15 + 30 capped at 40
    assert high_g["value"] > low_g["value"]
    assert low_g["low"] < low_g["value"] < low_g["high"]


def test_fair_value_none_without_forward_eps():
    assert outlook.compute_fair_value(None, 0.2) is None
    assert outlook.compute_fair_value(-1.0, 0.2) is None


def test_tags_growth_value_quality_leverage():
    growth = outlook.category_tags(
        rev_growth=0.25,
        pe=40,
        pb=8,
        roe=0.2,
        net_margin=0.2,
        debt_to_equity=2.0,
        net_income=100,
    )
    assert "growth" in growth and "quality" in growth and "high-leverage" in growth
    value = outlook.category_tags(
        rev_growth=0.02,
        pe=10,
        pb=1.2,
        roe=0.05,
        net_margin=0.05,
        debt_to_equity=0.3,
        net_income=-5,
    )
    assert "value" in value and "unprofitable" in value


def test_horizons_cover_all_with_capped_confidence():
    rets = {"5d": 0.02, "10d": 0.03, "21d": 0.05, "126d": 0.1, "252d": 0.2}
    out = outlook.horizon_outlook(
        returns=rets, upside_pct=30.0, rev_growth=0.2, roe=0.2, net_margin=0.2
    )
    assert [h["horizon"] for h in out] == outlook.HORIZONS
    for h in out:
        assert h["label"] in ("buy", "sell", "neutral")
        assert 0 <= h["confidence"] <= 100
    by = {h["horizon"]: h for h in out}
    assert by["1d"]["confidence"] <= 45  # short horizon confidence-capped
    assert by["1y"]["label"] == "buy"  # strong upside + growth


def test_returns_from_closes():
    closes = [float(i) for i in range(1, 30)]  # 1..29 rising
    r = outlook.returns_from_closes(closes)
    assert r["5d"] is not None and r["5d"] > 0
    assert r["252d"] is None  # not enough history
