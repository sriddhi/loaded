"""Tests for the signal job: quote fetch, tick, multi-symbol, query helpers."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.signals import job  # noqa: E402


def test_signals_enabled_default_true():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SIGNALS_DISABLED", None)
        assert job.signals_enabled() is True
    with patch.dict(os.environ, {"SIGNALS_DISABLED": "true"}):
        assert job.signals_enabled() is False


def test_tracks_spy_mu_avgo():
    assert job.SYMBOLS == ["SPY", "MU", "AVGO"]


@pytest.mark.asyncio
async def test_fetch_quote_parses_price_and_volume():
    with patch("app.signals.job._fetch_quote_sync", MagicMock(return_value=(512.34, 1_000_000))):
        assert await job.fetch_quote("SPY") == (512.34, 1_000_000)


@pytest.mark.asyncio
async def test_tick_once_skips_without_quote():
    pool = MagicMock()
    with patch("app.signals.job.fetch_quote", AsyncMock(return_value=None)):
        assert await job.tick_once(pool, "MU") is None


@pytest.mark.asyncio
async def test_tick_once_stores_and_returns_signal():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetch = AsyncMock(return_value=[{"price": 100 + i, "volume": 1000 + i} for i in range(6)])
    conn.fetchval = AsyncMock(return_value=datetime.now(UTC))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    with patch("app.signals.job.fetch_quote", AsyncMock(return_value=(108.0, 2000))):
        result = await job.tick_once(pool, "AVGO")
    assert result is not None
    assert result["symbol"] == "AVGO"
    assert result["price"] == 108.0
    assert result["volume"] == 2000
    assert {s["horizon_min"] for s in result["signals"]} == {1, 5, 10, 20, 1440}
    assert all(s["reason"] for s in result["signals"])  # every rating has a reason
    conn.fetchval.assert_awaited_once()  # inserted a row


def test_row_to_signal_coerces_null_label_to_neutral():
    # Rows predating the 1m migration have sig_1m = None; must not crash.
    row = {
        "ts": datetime.now(UTC),
        "symbol": "SPY",
        "price": 100.0,
        "volume": 0,
        "sig_1m": None,
        "conf_1m": None,
        "reason_1m": None,
        "res_1m": None,
        "sig_5m": "bullish",
        "conf_5m": 0.5,
        "reason_5m": "up",
        "res_5m": "correct",
        "sig_10m": "neutral",
        "conf_10m": 0.0,
        "reason_10m": "flat",
        "res_10m": None,
        "sig_20m": "bearish",
        "conf_20m": 0.3,
        "reason_20m": "down",
        "res_20m": None,
        "sig_1d": "neutral",
        "conf_1d": 0.0,
        "reason_1d": "flat",
        "res_1d": None,
    }
    out = job._row_to_signal(row)
    one_min = next(s for s in out["signals"] if s["horizon_min"] == 1)
    assert one_min["label"] == "neutral"
    assert one_min["outcome"] == "pending"


@pytest.mark.asyncio
async def test_tick_all_runs_every_symbol():
    calls: list[str] = []

    async def _fake_tick(_pool, symbol):
        calls.append(symbol)
        return {"symbol": symbol, "price": 1.0, "volume": 1, "signals": []}

    pool = MagicMock()
    with patch("app.signals.job.tick_once", _fake_tick):
        results = await job.tick_all(pool)
    assert calls == job.SYMBOLS
    assert [r["symbol"] for r in results] == job.SYMBOLS
