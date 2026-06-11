"""Tests for deterministic forward P/E."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.fundamentals import forward as fwd  # noqa: E402


@pytest.fixture(autouse=True)
def _clear():
    fwd._cache.clear()
    yield
    fwd._cache.clear()


@pytest.mark.asyncio
async def test_forward_pe_computed_at_current_price():
    base = {"forward_eps": 5.0, "trailing_eps": 4.0, "forward_pe_provider": 18.0}
    with patch("app.fundamentals.forward._fetch_forward", return_value=base):
        out = await fwd.forward_metrics("AAPL", price=100.0)
    assert out["forward_eps"] == 5.0
    assert out["forward_pe"] == 20.0  # 100 / 5 at OUR price, not the provider's 18


@pytest.mark.asyncio
async def test_forward_pe_none_when_no_estimate():
    base = {"forward_eps": None, "trailing_eps": 4.0, "forward_pe_provider": None}
    with patch("app.fundamentals.forward._fetch_forward", return_value=base):
        out = await fwd.forward_metrics("KO", price=60.0)
    assert out["forward_eps"] is None
    assert out["forward_pe"] is None  # shown as "—", never guessed


@pytest.mark.asyncio
async def test_forward_pe_none_when_no_price():
    base = {"forward_eps": 5.0, "trailing_eps": 4.0, "forward_pe_provider": 18.0}
    with patch("app.fundamentals.forward._fetch_forward", return_value=base):
        out = await fwd.forward_metrics("AAPL", price=None)
    assert out["forward_pe"] is None


@pytest.mark.asyncio
async def test_result_cached_within_ttl():
    base = {"forward_eps": 5.0, "trailing_eps": 4.0, "forward_pe_provider": 18.0}
    with patch("app.fundamentals.forward._fetch_forward", return_value=base) as f:
        await fwd.forward_metrics("AAPL", price=100.0)
        await fwd.forward_metrics("AAPL", price=110.0)
    f.assert_called_once()  # second call hits the cache


def test_num_filters_nan_and_zero():
    assert fwd._num(float("nan")) is None
    assert fwd._num(0) is None
    assert fwd._num(12.5) == 12.5
    assert fwd._num(None) is None
