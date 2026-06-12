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


def test_paper_reports_list_and_detail(tmp_path, monkeypatch):
    import json as _json

    import app.ops.router as ops_router

    monkeypatch.setattr(ops_router, "_REPORT_DIR", str(tmp_path))
    sample = {
        "underlyings": ["SPY", "MU"],
        "combined": {"decisions": 3, "right": 2, "wrong": 1, "total_upside_usd": 14.0},
        "trades": [],
    }
    (tmp_path / "2026-06-15.json").write_text(_json.dumps(sample))
    (tmp_path / "latest.json").write_text(_json.dumps(sample))  # excluded from list

    tc = _client()
    resp = tc.get("/ops/paper/reports")
    assert resp.status_code == 200
    reports = resp.json()["reports"]
    assert [r["date"] for r in reports] == ["2026-06-15"]
    assert reports[0]["combined"]["decisions"] == 3

    detail = tc.get("/ops/paper/reports/2026-06-15")
    assert detail.status_code == 200
    assert detail.json()["underlyings"] == ["SPY", "MU"]

    assert tc.get("/ops/paper/reports/2026-06-16").status_code == 404
    assert tc.get("/ops/paper/reports/not-a-date").status_code == 422
