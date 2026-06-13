"""Insights composition — empty-safe sections, macro impact weighting."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.portfolio.insights import _macro_impacts, build_insights  # noqa: E402


def _pool(score_rows=None, fired_rows=None, earnings_rows=None):
    pool = MagicMock()
    pool.fetch = AsyncMock(side_effect=[score_rows or [], fired_rows or [], earnings_rows or []])
    return pool


def _holding(sym: str, sector: str, weight: float):
    return {
        "symbol": sym,
        "sector": sector,
        "weight_pct": weight,
        "market_value": weight * 100,
        "cost_basis": weight * 100,
        "qty": 1,
        "price": weight * 100,
    }


@pytest.mark.asyncio
async def test_empty_everything_never_raises():
    out = await build_insights(_pool(), [], 0.0)
    assert out["holdings_signals"]["summary"] == "No screener scores yet"
    assert out["holdings_signals"]["items"] == []
    assert out["macro_impacts"] == []
    assert out["upcoming_earnings"] == []
    assert out["health"]["diversification_score"] == 0
    assert len(out["health"]["checks"]) == 6


@pytest.mark.asyncio
async def test_sell_rank_summary_counts():
    holdings = [_holding("AAA", "Energy", 60.0), _holding("BBB", "Utilities", 40.0)]
    scores = [
        {"symbol": "AAA", "composite": 30.0, "candidate": "sell", "rank": 400, "reasons": "[]"},
        {"symbol": "BBB", "composite": 70.0, "candidate": "buy", "rank": 10, "reasons": "[]"},
    ]
    out = await build_insights(_pool(score_rows=scores), holdings, 0.0)
    assert out["holdings_signals"]["summary"] == "1 holding now ranks sell"
    assert len(out["holdings_signals"]["items"]) == 2


@pytest.mark.asyncio
async def test_macro_impacts_only_touch_held_sectors():
    holdings = [_holding("XLE", "Energy", 100.0)]
    fired = [
        {"alert_id": "claims_4wk_above_250k", "since": datetime.now(UTC)},  # CD/Staples → not held
        {
            "alert_id": "ppi_hot_core_rolling",
            "since": datetime.now(UTC),
        },  # Materials−, Energy+ → held
    ]
    out = await build_insights(_pool(fired_rows=fired), holdings, 0.0)
    ids = [m["alert_id"] for m in out["macro_impacts"]]
    assert ids == ["ppi_hot_core_rolling"]
    affected = out["macro_impacts"][0]["affected"]
    assert affected == [
        {"sector": "Energy", "portfolio_weight_pct": 100.0, "direction": "tailwind"}
    ]


def test_macro_impacts_pure_mapping():
    fired = [{"alert_id": "two_year_below_3_5", "meaning": "m", "impact": "i", "fired_since": None}]
    out = _macro_impacts(fired, {"Utilities": 30.0, "Energy": 70.0})
    assert out and out[0]["affected"][0]["sector"] == "Utilities"
    assert out[0]["affected"][0]["direction"] == "tailwind"
    assert _macro_impacts(fired, {"Energy": 100.0}) == []  # no mapped sector held
