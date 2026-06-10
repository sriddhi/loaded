"""Tests for the Finnhub health shim."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.fundamentals.client import finnhub_ok  # noqa: E402
from app.fundamentals.finnhub_ws import FinnhubWsClient  # noqa: E402
from app.fundamentals.price_cache import InMemoryPriceCache  # noqa: E402


def test_missing_credentials():
    with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}):
        ok, err = finnhub_ok(None)
    assert ok is False
    assert err == "missing_credentials"


def test_not_started():
    with patch.dict(os.environ, {"FINNHUB_API_KEY": "abc"}):
        ok, err = finnhub_ok(None)
    assert ok is False
    assert err == "not_started"


def test_connecting_then_connected():
    client = FinnhubWsClient("abc", InMemoryPriceCache(), ["NVDA"])
    with patch.dict(os.environ, {"FINNHUB_API_KEY": "abc"}):
        assert finnhub_ok(client) == (False, "connecting")
        client.connected = True
        assert finnhub_ok(client) == (True, None)
