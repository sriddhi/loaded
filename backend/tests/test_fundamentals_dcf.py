"""Tests for the Buffett-grade DCF — formulas, caps/floors, and quality gates."""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.fundamentals import dcf  # noqa: E402
from app.fundamentals.models import EquityFinancials  # noqa: E402


def _stmt(
    year: int,
    *,
    ocf: int,
    capex: int,
    revenue: int,
    debt: int = 0,
    cash: int = 0,
    equity: int = 1_000_000_00,
    shares: int = 1_000_000,
) -> EquityFinancials:
    return EquityFinancials(
        symbol="TEST",
        period_type="annual",
        period_end=date(year, 12, 31),
        fiscal_year=year,
        operating_cash_flow=ocf,
        capex=capex,
        revenue=revenue,
        total_debt=debt,
        cash_and_equiv=cash,
        total_equity=equity,
        shares_diluted=shares,
    )


def _steady_series(oe_dollars: float = 10_000_000.0, n: int = 5) -> list[EquityFinancials]:
    """Flat owner earnings of `oe_dollars` (OCF in cents, capex 0), newest-first."""
    cents = int(oe_dollars * 100)
    return [_stmt(2026 - i, ocf=cents, capex=0, revenue=100_000_00) for i in range(n)]


# ── Owner earnings + hand-computed two-stage fixture ───────────────────────────


def test_owner_earnings_is_ocf_minus_abs_capex():
    s = [_stmt(2026, ocf=500_00, capex=-200_00, revenue=1_000_00)]
    assert dcf.owner_earnings_series(s) == [300.0]  # 500 − |−200| in dollars


def test_two_stage_pv_matches_hand_computation():
    # Zero stage-1 growth, 10% discount. Years 6-10 fade linearly from 0 up to
    # the 2.5% terminal rate (the model always converges to terminal growth).
    base, g, d = 100.0, 0.0, 0.10
    tg = min(0.025, d - 0.01)  # 0.025
    flows, flow = [], base
    for year in range(1, 11):
        gy = g if year <= 5 else g - ((g - tg) / 5) * (year - 5)
        flow *= 1 + gy
        flows.append(flow)
    pv = sum(f / (1 + d) ** (i + 1) for i, f in enumerate(flows))
    pv += (flows[-1] * (1 + tg) / (d - tg)) / (1 + d) ** 10
    got = dcf.two_stage_dcf(base, g, d)
    assert abs(got - pv) / pv < 1e-9


def test_two_stage_fade_hand_fixture():
    # growth 10%, discount 10% → terminal 2.5%, fade step (0.10−0.025)/5 = 0.015.
    base, g, d = 100.0, 0.10, 0.10
    tg = 0.025
    flows, flow = [], base
    for year in range(1, 11):
        gy = g if year <= 5 else g - ((g - tg) / 5) * (year - 5)
        flow *= 1 + gy
        flows.append(flow)
    pv = sum(f / (1 + d) ** (i + 1) for i, f in enumerate(flows))
    pv += (flows[-1] * (1 + tg) / (d - tg)) / (1 + d) ** 10
    got = dcf.two_stage_dcf(base, g, d)
    assert abs(got - pv) / pv < 1e-9


# ── Caps, floors, clamps ───────────────────────────────────────────────────────


def test_growth_capped_at_15_pct_and_floored_at_zero():
    # Explosive history → capped at 0.15.
    fast = [
        _stmt(
            2026 - i,
            ocf=int(100_00 * (1.5 ** (5 - i))),
            capex=0,
            revenue=int(100_00 * (1.5 ** (5 - i))),
        )
        for i in range(6)
    ]
    oe = [v for v in dcf.owner_earnings_series(fast) if v is not None]
    assert dcf.derive_growth(fast, oe) == 0.15
    # Declining history → floored at 0, not negative.
    decl = [
        _stmt(
            2026 - i,
            ocf=int(100_00 * (0.8 ** (5 - i))),
            capex=0,
            revenue=int(100_00 * (0.8 ** (5 - i))),
        )
        for i in range(6)
    ]
    oe2 = [v for v in dcf.owner_earnings_series(decl) if v is not None]
    assert dcf.derive_growth(decl, oe2) == 0.0


def test_discount_floor_and_leverage_penalty(monkeypatch):
    monkeypatch.setenv("DCF_DISCOUNT_RATE", "0.05")  # below floor
    assert dcf.discount_rate(None) == 0.08
    monkeypatch.setenv("DCF_DISCOUNT_RATE", "0.10")
    assert dcf.discount_rate(0.5) == 0.10
    assert abs(dcf.discount_rate(1.5) - 0.12) < 1e-12  # +2% leverage penalty


def test_margin_of_safety_clamped_both_ends():
    assert dcf.margin_of_safety(None, None, roic=0.20) == 0.25  # 0.30−0.05
    assert dcf.margin_of_safety(0.5, 2.0, roic=None) == 0.50  # 0.30+0.10+0.10
    assert dcf.margin_of_safety(None, None, None) == 0.30


# ── Quality gates ──────────────────────────────────────────────────────────────


def test_gate_insufficient_history():
    out = dcf.run_dcf(_steady_series(n=3), price=10.0)
    assert out["verdict"] == "not_valuable"
    assert any("insufficient history" in f for f in out["gate_failures"])
    assert "intrinsic_per_share" not in out  # no fabricated number


def test_gate_negative_owner_earnings():
    s = _steady_series(n=5)
    s[0] = _stmt(2026, ocf=-100_00, capex=0, revenue=100_000_00)
    out = dcf.run_dcf(s, price=10.0)
    assert out["verdict"] == "not_valuable"
    assert any("non-positive" in f for f in out["gate_failures"])


def test_gate_erratic_cash_flows():
    vals = [500_00, 50_00, 700_00, 20_00, 600_00]  # wildly erratic
    s = [_stmt(2026 - i, ocf=vals[i], capex=0, revenue=100_000_00) for i in range(5)]
    out = dcf.run_dcf(s, price=10.0)
    assert out["verdict"] == "not_valuable"
    assert any("erratic" in f for f in out["gate_failures"])


def test_gate_missing_shares():
    s = _steady_series(n=5)
    s[0] = _stmt(2026, ocf=100_00, capex=0, revenue=100_000_00, shares=0)
    out = dcf.run_dcf(s, price=10.0)
    assert out["verdict"] == "not_valuable"
    assert any("share count" in f for f in out["gate_failures"])


# ── Bridge, sensitivity, verdicts ──────────────────────────────────────────────


def test_net_debt_reduces_intrinsic():
    rich = dcf.run_dcf(_steady_series(), price=None)
    indebted_series = [
        _stmt(2026 - i, ocf=100_00, capex=0, revenue=100_000_00, debt=1_000_000_000, cash=0)
        for i in range(5)
    ]
    indebted = dcf.run_dcf(indebted_series, price=None)
    assert indebted["intrinsic_per_share"] < rich["intrinsic_per_share"]


def test_sensitivity_grid_shape_and_monotonicity():
    out = dcf.run_dcf(_steady_series(), price=None)
    grid = out["sensitivity"]
    assert len(grid) == 3 and all(len(r["cells"]) == 3 for r in grid)
    for row in grid:  # intrinsic falls as discount rises
        vals = [c["intrinsic"] for c in row["cells"]]
        assert vals[0] > vals[1] > vals[2]
    # intrinsic rises with growth at a fixed discount
    col = [r["cells"][1]["intrinsic"] for r in grid]
    assert col[0] <= col[1] <= col[2]


def test_verdicts_and_assumptions_echoed():
    out = dcf.run_dcf(_steady_series(), price=None)
    intrinsic, buy_below = out["intrinsic_per_share"], out["buy_below"]
    assert buy_below < intrinsic
    cheap = dcf.run_dcf(_steady_series(), price=buy_below * 0.9)
    fair = dcf.run_dcf(_steady_series(), price=(buy_below + intrinsic) / 2)
    rich = dcf.run_dcf(_steady_series(), price=intrinsic * 1.5)
    assert (cheap["verdict"], fair["verdict"], rich["verdict"]) == (
        "undervalued",
        "fair",
        "overvalued",
    )
    a = out["assumptions"]
    for key in (
        "base_owner_earnings_usd",
        "stage1_growth",
        "terminal_growth",
        "discount_rate",
        "margin_of_safety",
        "net_debt_usd",
        "shares",
    ):
        assert key in a
    assert "not financial advice" in out["disclaimer"]


def test_explanation_present_for_valued_and_refused():
    valued = dcf.run_dcf(_steady_series(), price=100.0)
    assert "owner earnings" in valued["explanation"].lower()
    assert "intrinsic value" in valued["explanation"].lower()
    refused = dcf.run_dcf(_steady_series(n=3), price=10.0)
    assert "predictability" in refused["explanation"].lower()
    assert "declines to print" in refused["explanation"].lower()
