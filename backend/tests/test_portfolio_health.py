"""Health checks, diversification score and sizing suggestions."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.portfolio.health import (  # noqa: E402
    diversification_score,
    run_health_checks,
    suggest_allocation,
)


def _h(sym: str, value: float, sector: str = "Information Technology", price: float = 100.0):
    return {
        "symbol": sym,
        "sector": sector,
        "market_value": value,
        "cost_basis": value,
        "qty": value / price,
        "price": price,
        "weight_pct": None,
    }


def _check(checks: list[dict], cid: str) -> dict:
    return next(c for c in checks if c["id"] == cid)


def test_position_concentration_thresholds():
    # 25% position → flag
    holdings = [_h("A", 25.0), _h("B", 75.0)]
    assert _check(run_health_checks(holdings, 0.0), "position_concentration")["status"] == "flag"
    # 15% → warn; ≤10% → ok
    holdings = [_h("A", 15.0)] + [_h(f"X{i}", 8.5) for i in range(10)]
    assert _check(run_health_checks(holdings, 0.0), "position_concentration")["status"] == "warn"
    holdings = [_h(f"X{i}", 10.0) for i in range(10)]
    assert _check(run_health_checks(holdings, 0.0), "position_concentration")["status"] == "ok"


def test_sector_overweight_and_breadth_and_hhi():
    # 100% IT vs 33% reference → +67pts → flag; 1 holding → breadth flag; HHI 1 → flag
    checks = run_health_checks([_h("A", 100.0)], 0.0)
    assert _check(checks, "sector_overweight")["status"] == "flag"
    assert _check(checks, "min_breadth")["status"] == "flag"
    assert _check(checks, "hhi")["status"] == "flag"
    # 12 equal-weight names across sectors → all ok
    sectors = ["Financials", "Health Care", "Energy", "Utilities", "Materials", "Industrials"]
    holdings = [_h(f"S{i}", 10.0, sectors[i % 6]) for i in range(12)]
    checks = run_health_checks(holdings, 0.0)
    assert _check(checks, "min_breadth")["status"] == "ok"
    assert _check(checks, "hhi")["status"] == "ok"


def test_cash_drag_and_sell_quality():
    holdings = [_h(f"S{i}", 10.0) for i in range(10)]
    assert _check(run_health_checks(holdings, 25.0), "cash_drag")["status"] == "info"
    assert _check(run_health_checks(holdings, 10.0), "cash_drag")["status"] == "ok"
    scores = {
        "S0": {"candidate": "sell"},
        "S1": {"candidate": "strong_sell"},
        "S2": {"candidate": "sell"},
    }
    out = _check(run_health_checks(holdings, 0.0, scores), "score_quality")
    assert out["status"] == "warn" and out["metric"] == 30.0  # 3×10%
    assert (
        _check(run_health_checks(holdings, 0.0, {"S0": {"candidate": "sell"}}), "score_quality")[
            "status"
        ]
        == "ok"
    )


def test_diversification_score_bounds():
    assert diversification_score([]) == 0
    one = diversification_score([_h("A", 100.0)])
    many = diversification_score(
        [
            _h(f"S{i}", 10.0, s)
            for i, s in enumerate(
                [
                    "Financials",
                    "Health Care",
                    "Energy",
                    "Utilities",
                    "Materials",
                    "Industrials",
                    "Real Estate",
                    "Consumer Staples",
                    "Communication Services",
                    "Information Technology",
                    "Consumer Discretionary",
                    "Financials",
                    "Energy",
                    "Utilities",
                    "Materials",
                ]
            )
        ]
    )
    assert 0 <= one < many <= 100
    assert many >= 90  # 15 names, 10+ sectors, equal weight


def test_suggestions_caps_and_modes():
    holdings = [_h("A", 500.0), _h("B", 100.0)]
    # equal weight: tops up the underweight B first
    out = suggest_allocation(200.0, "equal_weight", holdings, [])
    assert out and out[0]["symbol"] == "B" and out[0]["action"] == "add"
    # score weighted: only unheld buy candidates, 10% cap
    candidates = [
        {
            "symbol": "A",
            "composite": 90.0,
            "candidate": "strong_buy",
            "price": 100.0,
        },  # held → skip
        {"symbol": "NEW1", "composite": 80.0, "candidate": "buy", "price": 50.0},
        {"symbol": "NEW2", "composite": 40.0, "candidate": "buy", "price": 50.0},
    ]
    out = suggest_allocation(1000.0, "score_weighted", holdings, candidates, top_n=5)
    symbols = {s["symbol"] for s in out}
    assert "A" not in symbols and "NEW1" in symbols
    total_after = 600.0 + 1000.0
    for s in out:
        assert s["est_cost"] <= total_after * 0.10 + 1e-6  # 10% cap
    # zero cash → nothing
    assert suggest_allocation(0.0, "score_weighted", holdings, candidates) == []
    # tiny suggestion skipped (< 0.1 share)
    tiny = suggest_allocation(
        2.0,
        "score_weighted",
        [],
        [{"symbol": "PRICY", "composite": 90.0, "candidate": "buy", "price": 1000.0}],
    )
    assert tiny == []
