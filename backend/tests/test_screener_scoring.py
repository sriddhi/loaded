"""Scoring engine: determinism, missing-data tolerance, label ladder."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.screener.scoring import (  # noqa: E402
    SymbolInputs,
    composite,
    label,
    score_analyst,
    score_growth,
    score_macro_fit,
    score_momentum,
    score_quality,
    score_symbol,
    score_value,
)


def _stmt(year: int, rev: int, ni: int, eps: float) -> dict:
    return {
        "symbol": "TEST",
        "period_type": "annual",
        "period_end": f"{year}-12-31",
        "revenue": rev,
        "net_income": ni,
        "gross_profit": int(rev * 0.5),
        "total_equity": 50_000_000_00,
        "total_debt": 20_000_000_00,
        "current_assets": 30_000_000_00,
        "current_liabilities": 15_000_000_00,
        "eps_diluted": eps,
        "operating_cash_flow": int(ni * 1.2),
        "capex": -int(ni * 0.2),
        "cash_and_equiv": 10_000_000_00,
        "shares_diluted": 1_000_000,
    }


def _inputs() -> SymbolInputs:
    closes = [100 + i * 0.2 for i in range(260)]
    return SymbolInputs(
        symbol="TEST",
        sector="Information Technology",
        statements=[
            _stmt(2025, 120_000_000_00, 24_000_000_00, 6.0),
            _stmt(2024, 105_000_000_00, 20_000_000_00, 5.0),
            _stmt(2023, 95_000_000_00, 17_000_000_00, 4.2),
            _stmt(2022, 88_000_000_00, 15_000_000_00, 3.8),
        ],
        analyst={"target_price_mean": 180.0, "recommendation": "buy", "num_analysts": 20},
        closes=closes,
        price=closes[-1],
        fired_alert_ids={"smh_50dma"},
        sector_pe_median=30.0,
    )


def test_determinism():
    a = score_symbol(_inputs())
    b = score_symbol(_inputs())
    assert a == b


def test_each_pillar_tolerates_missing_alone():
    empty = SymbolInputs(symbol="X")
    for fn in (
        score_value,
        score_quality,
        score_growth,
        score_momentum,
        score_analyst,
        score_macro_fit,
    ):
        s, reasons = fn(empty)
        assert s is None and reasons == []
    out = score_symbol(empty)
    assert out["composite"] is None and out["candidate"] == "hold"
    assert any("insufficient data" in r for r in out["reasons"])


def test_composite_renormalizes_and_coverage():
    comp, cov = composite(
        {
            "value": 80.0,
            "quality": None,
            "growth": None,
            "momentum": None,
            "analyst": None,
            "macro_fit": None,
        }
    )
    assert comp == 80.0  # single pillar renormalizes to itself
    assert cov == round(0.25, 3)


def test_label_ladder_boundaries():
    assert label(75.0, 0.8, 60.0, 60.0) == "strong_buy"
    assert label(75.0, 0.8, 59.0, 60.0) == "buy"  # value gate fails → buy tier
    assert label(60.0, 0.6, 50.0, 50.0) == "buy"
    assert label(59.9, 0.6, 50.0, 50.0) == "hold"
    assert label(39.9, 0.6, 50.0, 50.0) == "sell"
    assert label(24.9, 0.8, 40.0, 40.0) == "strong_sell"
    assert label(24.9, 0.7, 40.0, 40.0) == "sell"  # coverage gate fails → sell tier
    assert label(80.0, 0.4, 90.0, 90.0) == "hold"  # low coverage forces hold
    assert label(None, 1.0, None, None) == "hold"


def test_scores_clamped_0_100():
    out = score_symbol(_inputs())
    for s in out["pillars"].values():
        if s is not None:
            assert 0.0 <= s <= 100.0
    assert out["coverage"] == 1.0


def test_macro_tilt_only_fired_and_mapped():
    inp = SymbolInputs(symbol="X", sector="Information Technology", fired_alert_ids=set())
    s, _ = score_macro_fit(inp)
    assert s == 50.0  # nothing fired → neutral
    inp2 = SymbolInputs(
        symbol="X", sector="Information Technology", fired_alert_ids={"smh_50dma", "unknown_alert"}
    )
    s2, reasons = score_macro_fit(inp2)
    assert s2 == 60.0  # +10 from smh_50dma; unknown contributes 0
    assert reasons and "smh_50dma" in reasons[0]


def test_momentum_needs_history():
    s, _ = score_momentum(SymbolInputs(symbol="X", closes=[100.0] * 100))
    assert s is None  # < 210 closes


def test_analyst_low_coverage_shrinks():
    full = score_analyst(
        SymbolInputs(
            symbol="X",
            price=100.0,
            analyst={"target_price_mean": 130.0, "recommendation": "buy", "num_analysts": 20},
        )
    )[0]
    thin = score_analyst(
        SymbolInputs(
            symbol="X",
            price=100.0,
            analyst={"target_price_mean": 130.0, "recommendation": "buy", "num_analysts": 2},
        )
    )[0]
    assert full is not None and thin is not None
    assert abs(thin - 50) < abs(full - 50)  # shrunk toward neutral
