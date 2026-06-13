"""Unit tests for the on-demand metric engine + OOP models. No DB/network."""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.fundamentals.metrics import (  # noqa: E402
    FundamentalMetrics,
    MetricContext,
    available_metrics,
    to_ttm,
)
from app.fundamentals.models import (  # noqa: E402
    BaseFinancials,
    EquityFinancials,
    build_financials,
)


def _eq(period_end: str, **kw: object) -> EquityFinancials:
    base: dict[str, object] = {
        "symbol": "TEST",
        "period_type": "annual",
        "period_end": date.fromisoformat(period_end),
    }
    base.update(kw)
    return EquityFinancials(**base)  # type: ignore[arg-type]


def _ctx(latest: EquityFinancials, series: list[EquityFinancials], price: float | None = None):
    return MetricContext(latest=latest, series=series, period_type="annual", live_price=price)


# ── Models / registry ─────────────────────────────────────────────────────────


def test_build_financials_defaults_to_equity():
    f = build_financials("us_equity", symbol="X", period_type="annual", period_end=date(2024, 1, 1))
    assert isinstance(f, EquityFinancials)


def test_unknown_asset_class_falls_back_to_equity():
    f = build_financials(
        "klingon_bonds", symbol="X", period_type="annual", period_end=date(2024, 1, 1)
    )
    assert isinstance(f, EquityFinancials)
    assert f.asset_class == "klingon_bonds"


def test_gross_margin_computed_field():
    f = _eq("2024-12-31", revenue=100_00, gross_profit=40_00)
    assert f.gross_margin == 0.4


def test_models_are_frozen():
    f = _eq("2024-12-31", revenue=100)
    import pydantic

    try:
        f.revenue = 200  # type: ignore[misc]
        raise AssertionError("expected frozen model to reject mutation")
    except pydantic.ValidationError:
        pass


# ── Margins / returns / leverage ──────────────────────────────────────────────


def test_basic_ratios():
    f = _eq(
        "2024-12-31",
        revenue=1000_00,
        gross_profit=400_00,
        operating_income=200_00,
        net_income=100_00,
        total_assets=2000_00,
        total_equity=500_00,
        total_debt=300_00,
        current_assets=600_00,
        current_liabilities=300_00,
        inventory=100_00,
    )
    m, unknown = FundamentalMetrics(_ctx(f, [f])).compute(
        [
            "gross_margin",
            "net_margin",
            "roe",
            "roa",
            "debt_to_equity",
            "current_ratio",
            "quick_ratio",
        ]
    )
    assert unknown == []
    assert m["gross_margin"] == 0.4
    assert m["net_margin"] == 0.1
    assert m["roe"] == 0.2
    assert m["roa"] == 0.05
    assert m["debt_to_equity"] == 0.6
    assert m["current_ratio"] == 2.0
    assert m["quick_ratio"] == round((600 - 100) / 300, 6)


def test_negative_equity_roe_is_signed_not_none():
    f = _eq("2024-12-31", net_income=100_00, total_equity=-200_00)
    m, _ = FundamentalMetrics(_ctx(f, [f])).compute(["roe"])
    assert m["roe"] is not None and m["roe"] < 0


def test_missing_field_returns_none():
    f = _eq("2024-12-31", revenue=None, gross_profit=None)
    m, _ = FundamentalMetrics(_ctx(f, [f])).compute(["gross_margin", "roe"])
    assert m["gross_margin"] is None
    assert m["roe"] is None


# ── Growth / CAGR ─────────────────────────────────────────────────────────────


def test_revenue_growth_yoy_annual():
    cur = _eq("2024-12-31", revenue=110_00)
    prior = _eq("2023-12-31", revenue=100_00)
    m, _ = FundamentalMetrics(_ctx(cur, [cur, prior])).compute(["revenue_growth_yoy"])
    assert m["revenue_growth_yoy"] == 0.1


def test_cagr_insufficient_history_is_none():
    cur = _eq("2024-12-31", revenue=110_00)
    m, _ = FundamentalMetrics(_ctx(cur, [cur])).compute(["revenue_cagr_3y"])
    assert m["revenue_cagr_3y"] is None


def test_revenue_cagr_3y():
    series = [
        _eq("2024-12-31", revenue=200_00),
        _eq("2023-12-31", revenue=0),
        _eq("2022-12-31", revenue=0),
        _eq("2021-12-31", revenue=100_00),
    ]
    m, _ = FundamentalMetrics(_ctx(series[0], series)).compute(["revenue_cagr_3y"])
    assert m["revenue_cagr_3y"] == round(2 ** (1 / 3) - 1, 6)


# ── Valuation (needs live price) ──────────────────────────────────────────────


def test_valuation_none_without_price():
    f = _eq("2024-12-31", eps_diluted=5.0, revenue=1000_00, shares_outstanding=1000)
    m, _ = FundamentalMetrics(_ctx(f, [f], price=None)).compute(["pe", "ps"])
    assert m["pe"] is None
    assert m["ps"] is None


def test_pe_with_price():
    f = _eq("2024-12-31", eps_diluted=5.0)
    m, _ = FundamentalMetrics(_ctx(f, [f], price=100.0)).compute(["pe"])
    assert m["pe"] == 20.0


def test_unknown_metric_reported():
    f = _eq("2024-12-31", revenue=100_00)
    m, unknown = FundamentalMetrics(_ctx(f, [f])).compute(["gross_margin", "bogus_metric"])
    assert "bogus_metric" in unknown
    assert "gross_margin" in m


# ── TTM ───────────────────────────────────────────────────────────────────────


def test_to_ttm_sums_flow_keeps_stock():
    qs = [
        EquityFinancials(
            symbol="T",
            period_type="quarterly",
            period_end=date(2024, 12, 31),
            revenue=10_00,
            total_equity=500_00,
        ),
        EquityFinancials(
            symbol="T",
            period_type="quarterly",
            period_end=date(2024, 9, 30),
            revenue=10_00,
            total_equity=480_00,
        ),
        EquityFinancials(
            symbol="T",
            period_type="quarterly",
            period_end=date(2024, 6, 30),
            revenue=10_00,
            total_equity=460_00,
        ),
        EquityFinancials(
            symbol="T",
            period_type="quarterly",
            period_end=date(2024, 3, 31),
            revenue=10_00,
            total_equity=440_00,
        ),
    ]
    ttm = to_ttm(list(qs))
    assert ttm is not None
    assert ttm.period_type == "ttm"
    assert ttm.revenue == 40_00  # flow summed
    assert ttm.total_equity == 500_00  # stock = latest snapshot


def test_to_ttm_insufficient_quarters():
    qs: list[BaseFinancials] = [
        EquityFinancials(symbol="T", period_type="quarterly", period_end=date(2024, 12, 31))
    ]
    assert to_ttm(qs) is None


def test_available_metrics_nonempty():
    assert "pe" in available_metrics()
    assert "gross_margin" in available_metrics()
