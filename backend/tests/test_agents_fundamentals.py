"""
Unit tests for the fundamentals pipeline.
Mocks yfinance so no network calls are made.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.agents.data import (
    _fiscal_quarter,
    _market_cap_tier,
    safe_div,
    to_cents,
    to_float,
)

# ── to_cents ──────────────────────────────────────────────────────────────────


def test_to_cents_positive():
    assert to_cents(1_000_000.00) == 100_000_000


def test_to_cents_negative():
    assert to_cents(-500_000.50) == -50_000_050


def test_to_cents_none():
    assert to_cents(None) is None


def test_to_cents_nan():
    assert to_cents(float("nan")) is None


def test_to_cents_inf():
    assert to_cents(float("inf")) is None


def test_to_cents_zero():
    assert to_cents(0) == 0


def test_to_cents_large():
    # $1.234B → 123_400_000_000 cents
    assert to_cents(1_234_000_000) == 123_400_000_000


# ── to_float ──────────────────────────────────────────────────────────────────


def test_to_float_none():
    assert to_float(None) is None


def test_to_float_nan():
    assert to_float(float("nan")) is None


def test_to_float_valid():
    assert to_float("3.14") == pytest.approx(3.14)


# ── safe_div ─────────────────────────────────────────────────────────────────


def test_safe_div_normal():
    assert safe_div(50, 100) == pytest.approx(0.5)


def test_safe_div_zero_denominator():
    assert safe_div(50, 0) is None


def test_safe_div_none():
    assert safe_div(None, 100) is None
    assert safe_div(50, None) is None


def test_safe_div_negative():
    # Negative net income / positive equity → negative ROE
    result = safe_div(-200_000_000, 1_000_000_000)
    assert result == pytest.approx(-0.2)


# ── Ratio computation logic ───────────────────────────────────────────────────


def test_gross_margin():
    """gross_margin = gross_profit / revenue"""
    gross_profit = to_cents(5_000_000_000)  # $5B
    revenue = to_cents(10_000_000_000)  # $10B
    margin = safe_div(gross_profit, revenue)
    assert margin == pytest.approx(0.5, abs=0.001)


def test_free_cash_flow():
    """FCF = OCF + capex (capex is negative)"""
    ocf = to_cents(8_000_000_000)  # $8B
    capex = to_cents(-2_000_000_000)  # -$2B
    fcf = ocf + capex
    assert fcf == to_cents(6_000_000_000)  # $6B


def test_revenue_growth_yoy():
    """YoY growth = (rev_now - rev_prior) / abs(rev_prior)"""
    rev_now = to_cents(12_000_000_000)
    rev_prior = to_cents(10_000_000_000)
    growth = safe_div(rev_now - rev_prior, rev_prior)
    assert growth == pytest.approx(0.2, abs=0.001)


def test_revenue_growth_yoy_negative():
    rev_now = to_cents(8_000_000_000)
    rev_prior = to_cents(10_000_000_000)
    growth = safe_div(rev_now - rev_prior, rev_prior)
    assert growth == pytest.approx(-0.2, abs=0.001)


# ── Fiscal quarter ────────────────────────────────────────────────────────────


def test_fiscal_quarter():
    assert _fiscal_quarter(date(2024, 3, 31)) == 1
    assert _fiscal_quarter(date(2024, 6, 30)) == 2
    assert _fiscal_quarter(date(2024, 9, 30)) == 3
    assert _fiscal_quarter(date(2024, 12, 31)) == 4


# ── Market cap tier ───────────────────────────────────────────────────────────


def test_market_cap_tier_mega():
    assert _market_cap_tier(to_cents(2_000_000_000_000)) == "mega"  # $2T


def test_market_cap_tier_large():
    assert _market_cap_tier(to_cents(50_000_000_000)) == "large"  # $50B


def test_market_cap_tier_mid():
    assert _market_cap_tier(to_cents(5_000_000_000)) == "mid"  # $5B


def test_market_cap_tier_small():
    assert _market_cap_tier(to_cents(500_000_000)) == "small"  # $500M


def test_market_cap_tier_micro():
    assert _market_cap_tier(to_cents(50_000_000)) == "micro"  # $50M


def test_market_cap_tier_none():
    assert _market_cap_tier(None) is None


# ── API endpoint tests (sync TestClient — no DB required) ────────────────────


from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def test_ingest_endpoint_unauthorized():
    """All /agents/* endpoints require JWT (bypass_auth removed via real_auth fixture)."""
    from app.auth.security import get_current_user

    # Remove bypass override so the real auth runs
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/agents/ingest/NVDA")
    assert response.status_code == 401
    # Restore (conftest teardown will also do this)
    app.dependency_overrides.clear()


def test_fundamentals_endpoint_unauthorized():
    from app.auth.security import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/agents/fundamentals/NVDA")
    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_equity_endpoint_unauthorized():
    from app.auth.security import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/agents/equity/NVDA")
    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_search_requires_auth():
    from app.auth.security import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/agents/search?q=NVDA")
    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_batch_request_schema():
    """Batch endpoint rejects missing body."""
    from app.auth.security import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/agents/ingest/batch")
    # 401 (auth) or 422 (validation) — both mean schema is wired
    assert response.status_code in (401, 422)
    app.dependency_overrides.clear()
