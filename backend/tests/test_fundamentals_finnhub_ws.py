"""Tests for the Finnhub websocket consumer + price cache. No real network."""

from __future__ import annotations

import json
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from unittest.mock import patch  # noqa: E402

from app.fundamentals.finnhub_ws import (  # noqa: E402
    FREE_TIER_SYMBOL_CAP,
    FinnhubWsClient,
    finnhub_ws_enabled,
)
from app.fundamentals.price_cache import InMemoryPriceCache  # noqa: E402


def test_enabled_follows_env():
    with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}):
        assert finnhub_ws_enabled() is False
    with patch.dict(os.environ, {"FINNHUB_API_KEY": "abc"}):
        assert finnhub_ws_enabled() is True


def test_handle_trade_message_updates_cache():
    cache = InMemoryPriceCache()
    client = FinnhubWsClient("key", cache, ["NVDA"])
    raw = json.dumps(
        {"type": "trade", "data": [{"s": "NVDA", "p": 123.45, "t": 1700000000000, "v": 10}]}
    )
    client.handle_message(raw)
    hit = cache.get("NVDA")
    assert hit is not None
    assert hit == (123.45, 1700000000000)


def test_handle_non_trade_message_ignored():
    cache = InMemoryPriceCache()
    client = FinnhubWsClient("key", cache, ["NVDA"])
    client.handle_message(json.dumps({"type": "ping"}))
    assert cache.get("NVDA") is None


def test_subscribe_set_capped_at_50():
    cache = InMemoryPriceCache()
    symbols = [f"SYM{i}" for i in range(60)]
    client = FinnhubWsClient("key", cache, symbols)
    subs = client._subscribe_set()
    assert len(subs) == FREE_TIER_SYMBOL_CAP == 50


def test_price_cache_case_insensitive():
    cache = InMemoryPriceCache()
    cache.update("nvda", 100.0, 1)
    assert cache.get("NVDA") == (100.0, 1)
