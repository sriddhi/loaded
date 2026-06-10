"""Tests for the in-memory price cache."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.fundamentals.price_cache import InMemoryPriceCache, PriceStore  # noqa: E402


def test_update_and_get():
    c = InMemoryPriceCache()
    c.update("NVDA", 123.45, 1700000000000)
    assert c.get("NVDA") == (123.45, 1700000000000)


def test_get_missing_returns_none():
    assert InMemoryPriceCache().get("ZZZZ") is None


def test_symbol_case_insensitive():
    c = InMemoryPriceCache()
    c.update("nvda", 10.0, 1)
    assert c.get("NVDA") == (10.0, 1)


def test_implements_protocol():
    assert isinstance(InMemoryPriceCache(), PriceStore)


def test_len_tracks_symbols():
    c = InMemoryPriceCache()
    c.update("A", 1.0, 1)
    c.update("B", 2.0, 2)
    assert len(c) == 2
