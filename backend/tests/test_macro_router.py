"""Router tests for /macro (auth bypassed via conftest, pool mocked)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import app.macro.router  # noqa: E402, F401
from fastapi.testclient import TestClient  # noqa: E402


def _client() -> TestClient:
    from unittest.mock import MagicMock

    from app.main import app

    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[])
    app.state.pool = pool
    return TestClient(app, raise_server_exceptions=False)


def _stub_alerts() -> list[dict]:
    from app.macro.signals import evaluate_alerts, evaluate_technicals

    stub = evaluate_alerts({}) + evaluate_technicals({})
    for a in stub:
        a.update({"as_of": None, "fired_since": None, "meaning": "m", "impact": "i"})
    return stub


def test_trackers_shape():
    with (
        patch("app.macro.router.load_all", AsyncMock(return_value={})),
        patch("app.macro.router.evaluate_now", AsyncMock(return_value=_stub_alerts())),
    ):
        resp = _client().get("/macro/trackers")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["trackers"]) == 8
    ids = {t["id"] for t in body["trackers"]}
    assert "cpi_vs_wage_income" in ids and "ecb_and_bunds" in ids
    assert "not financial advice" in body["disclaimer"]
    # card alerts carry the explainer fields through
    card = next(t for t in body["trackers"] if t["id"] == "cpi_vs_wage_income")
    assert all("meaning" in a and "fired_since" in a for a in card["alerts"])


def test_alerts_endpoint():
    with patch("app.macro.router.evaluate_now", AsyncMock(return_value=_stub_alerts())):
        resp = _client().get("/macro/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["alerts"]) >= 14  # 11 FRED rules + 3 technicals
    assert body["fired"] == []  # no data → nothing fired
    assert all("meaning" in a and "impact" in a and "as_of" in a for a in body["alerts"])


def test_series_unknown_404():
    resp = _client().get("/macro/series/NOTASERIES")
    assert resp.status_code == 404


def test_series_known_ok():
    with patch(
        "app.macro.router.load_series",
        AsyncMock(return_value=[{"date": "2026-01-01", "value": 3.0}]),
    ):
        resp = _client().get("/macro/series/DGS2")
    assert resp.status_code == 200
    assert resp.json()["points"][0]["value"] == 3.0
