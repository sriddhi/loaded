"""Router test for /ops/overview (auth bypassed via conftest)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import app.ops.router  # noqa: E402, F401
from fastapi.testclient import TestClient  # noqa: E402


def _client() -> TestClient:
    from app.main import app

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)

    # _signal_insights calls fetchrow once per symbol (count) then once per horizon.
    # Route by query shape so the mock is robust to the number of tracked symbols.
    sym_row = {"n": 5, "last_ts": datetime.now(UTC), "first_ts": datetime.now(UTC)}
    hit_row = {"hits": 3, "total": 4, "pending": 1}
    conn.fetchrow = AsyncMock(
        side_effect=lambda query, *a: hit_row if "FILTER" in query else sym_row
    )

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    app.state.pool = pool
    return TestClient(app, raise_server_exceptions=False)


def test_overview_returns_jobs_api_and_insights():
    resp = _client().get("/ops/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs" in body
    assert "api" in body
    assert "api_totals" in body
    assert "insights" in body
    from app.signals.job import SYMBOLS

    assert len(body["insights"]["per_symbol"]) == len(SYMBOLS)
    assert len(body["insights"]["hit_rate"]) == 5  # 1m,5m,10m,20m,1d
    assert body["insights"]["hit_rate"][0]["accuracy"] == 0.75
