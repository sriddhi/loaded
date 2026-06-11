"""Router tests for the signals module (auth bypassed via conftest)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import app.signals.router  # noqa: E402, F401
from fastapi.testclient import TestClient  # noqa: E402

_SIGNAL = {
    "ts": datetime.now(UTC),
    "symbol": "MU",
    "price": 112.34,
    "volume": 5_000_000,
    "signals": [
        {"horizon_min": 5, "label": "bullish", "confidence": 0.6, "reason": "Up 0.3% on volume."},
        {"horizon_min": 10, "label": "neutral", "confidence": 0.1, "reason": "Flat."},
        {"horizon_min": 20, "label": "bear_trap", "confidence": 0.4, "reason": "Failed breakdown."},
        {
            "horizon_min": 1440,
            "label": "neutral",
            "confidence": 0.0,
            "reason": "No edge over 1 day.",
        },
    ],
}


def _client() -> TestClient:
    from app.main import app

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    app.state.pool = pool
    return TestClient(app, raise_server_exceptions=False)


def test_symbols_lists_tracked():
    resp = _client().get("/signals/symbols")
    assert resp.status_code == 200
    assert resp.json()["symbols"] == ["SPY", "MU", "AVGO", "MSFT", "IBM", "INTC"]


def test_latest_ok():
    with patch("app.signals.router.get_latest", AsyncMock(return_value=_SIGNAL)):
        resp = _client().get("/signals/MU/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "MU"
    assert body["price"] == 112.34
    assert body["volume"] == 5_000_000
    assert body["signals"][0]["label"] == "bullish"


def test_latest_404_when_none():
    with patch("app.signals.router.get_latest", AsyncMock(return_value=None)):
        resp = _client().get("/signals/SPY/latest")
    assert resp.status_code == 404


def test_unknown_symbol_404():
    resp = _client().get("/signals/TSLA/latest")
    assert resp.status_code == 404


def test_history_ok():
    with patch("app.signals.router.get_history", AsyncMock(return_value=[_SIGNAL, _SIGNAL])):
        resp = _client().get("/signals/AVGO/history?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()["signals"]) == 2
