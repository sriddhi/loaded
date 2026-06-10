"""Router tests for the SPY signals module (auth bypassed via conftest)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import app.signals.router  # noqa: E402, F401
from fastapi.testclient import TestClient  # noqa: E402

_SIGNAL = {
    "ts": datetime.now(UTC),
    "price": 512.34,
    "signals": [
        {"horizon_min": 5, "label": "bullish", "confidence": 0.6},
        {"horizon_min": 10, "label": "neutral", "confidence": 0.1},
        {"horizon_min": 20, "label": "bear_trap", "confidence": 0.4},
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


def test_latest_ok():
    with patch("app.signals.router.get_latest", AsyncMock(return_value=_SIGNAL)):
        resp = _client().get("/signals/spy/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["price"] == 512.34
    assert body["signals"][0]["label"] == "bullish"


def test_latest_404_when_none():
    with patch("app.signals.router.get_latest", AsyncMock(return_value=None)):
        resp = _client().get("/signals/spy/latest")
    assert resp.status_code == 404


def test_history_ok():
    with patch("app.signals.router.get_history", AsyncMock(return_value=[_SIGNAL, _SIGNAL])):
        resp = _client().get("/signals/spy/history?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()["signals"]) == 2


def test_run_now_ok():
    with patch("app.signals.router.tick_once", AsyncMock(return_value=_SIGNAL)):
        resp = _client().post("/signals/spy/run")
    assert resp.status_code == 200
    assert resp.json()["signals"][2]["label"] == "bear_trap"


def test_run_now_503_when_no_price():
    with patch("app.signals.router.tick_once", AsyncMock(return_value=None)):
        resp = _client().post("/signals/spy/run")
    assert resp.status_code == 503
