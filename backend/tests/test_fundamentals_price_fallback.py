"""Tests for the price resolver (websocket → REST fallback)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.fundamentals import price_fallback as pf  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_rest_cache():
    pf._rest_cache.clear()
    yield
    pf._rest_cache.clear()


@pytest.mark.asyncio
async def test_uses_websocket_when_present():
    cache = MagicMock()
    cache.get = MagicMock(return_value=(123.45, 1000))
    with patch("app.fundamentals.price_fallback._yf_price") as yf:
        out = await pf.resolve_price("AAPL", cache)
    assert out == (123.45, 1000, "websocket")
    yf.assert_not_called()  # no REST call needed


@pytest.mark.asyncio
async def test_falls_back_to_rest_when_no_tick():
    cache = MagicMock()
    cache.get = MagicMock(return_value=None)
    with patch("app.fundamentals.price_fallback._yf_price", return_value=88.0):
        out = await pf.resolve_price("HOOD", cache)
    assert out is not None
    assert out[0] == 88.0
    assert out[2] == "rest"


@pytest.mark.asyncio
async def test_rest_result_is_cached_within_ttl():
    cache = MagicMock()
    cache.get = MagicMock(return_value=None)
    with patch("app.fundamentals.price_fallback._yf_price", return_value=50.0) as yf:
        first = await pf.resolve_price("KO", cache)
        second = await pf.resolve_price("KO", cache)
    assert first[0] == second[0] == 50.0
    yf.assert_called_once()  # second call served from the REST cache


@pytest.mark.asyncio
async def test_returns_none_when_everything_fails():
    cache = MagicMock()
    cache.get = MagicMock(return_value=None)
    with patch("app.fundamentals.price_fallback._yf_price", return_value=None):
        out = await pf.resolve_price("ZZZZ", cache)
    assert out is None
