"""Router tests for /screener (auth bypassed as admin via conftest)."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from fastapi.testclient import TestClient  # noqa: E402


def _client(pool: MagicMock) -> TestClient:
    from app.main import app

    app.state.pool = pool
    return TestClient(app, raise_server_exceptions=False)


def _pool() -> MagicMock:
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchval = AsyncMock(return_value=None)
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


def _score_row() -> dict:
    return {
        "symbol": "AAPL",
        "name": "Apple",
        "sector": "Information Technology",
        "id": 1,
        "equity_id": 1,
        "score_date": date(2026, 6, 12),
        "composite": 81.0,
        "value_score": 70.0,
        "quality_score": 90.0,
        "growth_score": 75.0,
        "momentum_score": 80.0,
        "analyst_score": 85.0,
        "macro_fit_score": 60.0,
        "coverage": 1.0,
        "candidate": "strong_buy",
        "rank": 3,
        "price_cents": 29_100,
        "reasons": '["Value: DCF fair value (upside +8%)"]',
        "inputs": "{}",
        "created_at": None,
    }


def test_scores_empty_before_first_run():
    pool = _pool()
    resp = _client(pool).get("/screener/scores")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0 and body["items"] == [] and body["as_of"] is None


def test_scores_page_shape():
    pool = _pool()
    pool.fetchval = AsyncMock(side_effect=[date(2026, 6, 12), 1])
    pool.fetch = AsyncMock(return_value=[_score_row()])
    resp = _client(pool).get("/screener/scores")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["candidate"] == "strong_buy" and item["pillars"]["quality"] == 90.0
    assert item["price"] == 291.0 and item["reasons"]


def test_scores_rejects_bad_sort():
    resp = _client(_pool()).get("/screener/scores?sort=evil;DROP")
    assert resp.status_code == 422


def test_candidates_sell_side_uses_strong_sell():
    pool = _pool()
    pool.fetchval = AsyncMock(return_value=date(2026, 6, 12))
    pool.fetch = AsyncMock(return_value=[])
    resp = _client(pool).get("/screener/candidates?side=sell")
    assert resp.status_code == 200
    args = pool.fetch.await_args.args
    assert "strong_sell" in args[2] and "sell" in args[2]  # candidate ANY($2)
    assert "rank DESC" in args[0]  # worst first


def test_run_admin_and_lock():
    from app.screener.job import SCREENER_LOCK

    pool = _pool()
    with patch("app.screener.router.run_screener", AsyncMock(return_value={})):
        resp = _client(pool).post("/screener/run")
        assert resp.status_code == 202  # conftest user is admin
    # non-admin → 403
    from app.auth.security import get_current_user
    from app.main import app

    async def _client_user() -> dict:
        return {"id": 2, "email": "c@x.com", "role": "client", "is_active": True}

    app.dependency_overrides[get_current_user] = _client_user
    try:
        resp = _client(pool).post("/screener/run")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert not SCREENER_LOCK.locked()


def test_score_detail_404():
    pool = _pool()
    resp = _client(pool).get("/screener/scores/NOPE")
    assert resp.status_code == 404


def test_status_shape():
    pool = _pool()
    pool.fetchval = AsyncMock(side_effect=[None, 0])
    resp = _client(pool).get("/screener/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_score_date"] is None and body["running"] is False
