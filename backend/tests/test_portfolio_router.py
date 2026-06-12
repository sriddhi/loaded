"""Router tests for /portfolio (auth bypassed via conftest, pool mocked)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _row(**kw) -> dict:
    base = {
        "id": 1,
        "owner_id": 1,
        "name": "Growth",
        "kind": "manual",
        "cost_method": "average",
        "base_currency": "USD",
        "cash_cents": 100_000,
        "is_active": True,
        "last_synced_at": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(kw)
    return base


def _client(conn: MagicMock) -> TestClient:
    from app.main import app

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    app.state.pool = pool
    return TestClient(app, raise_server_exceptions=False)


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    return conn


def test_create_portfolio_201():
    conn = _conn()
    conn.fetchrow = AsyncMock(return_value=_row())
    resp = _client(conn).post("/portfolio", json={"name": "Growth"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Growth" and body["cash"] == 1000.0


def test_create_duplicate_409():
    conn = _conn()
    conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError("dup"))
    resp = _client(conn).post("/portfolio", json={"name": "Growth"})
    assert resp.status_code == 409


def test_other_users_portfolio_404():
    """Owner scoping: the SELECT includes owner_id; no row → 404, no leak."""
    conn = _conn()
    conn.fetchrow = AsyncMock(return_value=None)
    resp = _client(conn).get("/portfolio/999")
    assert resp.status_code == 404
    sql = conn.fetchrow.await_args.args[0]
    assert "owner_id = $2" in sql


def test_tx_shape_422_buy_without_symbol():
    conn = _conn()
    conn.fetchrow = AsyncMock(return_value=_row())
    resp = _client(conn).post(
        "/portfolio/1/transactions",
        json={"tx_type": "buy", "qty": 1, "price": 10, "trade_date": "2026-01-02"},
    )
    assert resp.status_code == 422


def test_tx_on_synced_portfolio_409():
    conn = _conn()
    conn.fetchrow = AsyncMock(return_value=_row(kind="alpaca_paper"))
    resp = _client(conn).post(
        "/portfolio/1/transactions",
        json={
            "tx_type": "buy",
            "symbol": "AAPL",
            "qty": 1,
            "price": 10,
            "trade_date": "2026-01-02",
        },
    )
    assert resp.status_code == 409


def test_tx_oversell_422():
    conn = _conn()
    conn.fetchrow = AsyncMock(return_value=_row())
    with patch(
        "app.portfolio.router.pdb.insert_transaction",
        AsyncMock(side_effect=ValueError("oversell: selling 5 AAPL but only 2 held")),
    ):
        resp = _client(conn).post(
            "/portfolio/1/transactions",
            json={
                "tx_type": "sell",
                "symbol": "AAPL",
                "qty": 5,
                "price": 10,
                "trade_date": "2026-01-02",
            },
        )
    assert resp.status_code == 422
    assert "oversell" in resp.json()["detail"]


def test_sync_unavailable_503():
    from app.portfolio.sync import AlpacaUnavailableError

    conn = _conn()
    with patch(
        "app.portfolio.router.sync_alpaca_paper",
        AsyncMock(side_effect=AlpacaUnavailableError("no creds")),
    ):
        resp = _client(conn).post("/portfolio/sync/alpaca")
    assert resp.status_code == 503


def test_holdings_disclaimer_present():
    conn = _conn()
    conn.fetchrow = AsyncMock(return_value=_row())
    conn.fetch = AsyncMock(return_value=[])
    resp = _client(conn).get("/portfolio/1/holdings")
    assert resp.status_code == 200
    assert "not financial advice" in resp.json()["disclaimer"]
