"""Router tests for the fundamentals module (auth bypassed via conftest)."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import app.fundamentals.router  # noqa: E402, F401
import pytest  # noqa: E402
from app.fundamentals.models import EquityFinancials  # noqa: E402
from app.fundamentals.price_cache import InMemoryPriceCache  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _bypass_freshness():
    # The lazy-TTL refresh path + as_of query are covered in test_fundamentals_refresh;
    # bypass them here so the router tests exercise routing/serialization only.
    from app.fundamentals import price_fallback

    price_fallback._rest_cache.clear()
    with (
        patch("app.fundamentals.router._refresh_then_track", AsyncMock(return_value=None)),
        patch("app.fundamentals.router._as_of", AsyncMock(return_value=None)),
    ):
        yield


def _mock_pool() -> MagicMock:
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool


def _client(price_cache: object | None = None) -> TestClient:
    from app.main import app

    app.state.pool = _mock_pool()
    app.state.price_cache = price_cache
    return TestClient(app, raise_server_exceptions=False)


_SERIES = [
    EquityFinancials(
        symbol="NVDA",
        period_type="annual",
        period_end=date(2024, 1, 31),
        revenue=1000_00,
        gross_profit=700_00,
        net_income=300_00,
        total_equity=600_00,
        eps_diluted=5.0,
        shares_outstanding=1000,
    )
]


def test_refresh_ok():
    with patch(
        "app.fundamentals.router.ingest_statements",
        AsyncMock(return_value={"symbol": "NVDA", "periods_written": 12, "elapsed_ms": 5}),
    ):
        resp = _client().post("/fundamentals/NVDA/refresh")
    assert resp.status_code == 200
    assert resp.json()["periods_written"] == 12


def test_refresh_unknown_symbol_404():
    with patch(
        "app.fundamentals.router.ingest_statements",
        AsyncMock(side_effect=ValueError("No data found for symbol: ZZZZ")),
    ):
        resp = _client().post("/fundamentals/ZZZZ/refresh")
    assert resp.status_code == 404


def test_statements_ok():
    with patch("app.fundamentals.router._load_series", AsyncMock(return_value=_SERIES)):
        resp = _client().get("/fundamentals/NVDA/statements?period=annual&type=all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["statements"][0]["gross_margin"] == 0.7  # computed field present


def test_statements_404_when_empty():
    with patch("app.fundamentals.router._load_series", AsyncMock(return_value=[])):
        resp = _client().get("/fundamentals/NVDA/statements")
    assert resp.status_code == 404


def test_metrics_subset_and_valuation_needs_price():
    # No websocket tick AND the REST fallback yields nothing → valuation stays None.
    with (
        patch("app.fundamentals.router._load_series", AsyncMock(return_value=_SERIES)),
        patch("app.fundamentals.price_fallback._yf_price", return_value=None),
    ):
        resp = _client(price_cache=None).get(
            "/fundamentals/NVDA/metrics?metrics=roe,pe&period=annual"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["metrics"]) == {"roe", "pe"}
    assert body["metrics"]["roe"] == 0.5
    assert body["metrics"]["pe"] is None  # no price anywhere
    assert body["price_used"] is None


def test_metrics_uses_rest_fallback_when_no_tick():
    # No websocket tick, but the REST fallback returns a price → valuation computes.
    with (
        patch("app.fundamentals.router._load_series", AsyncMock(return_value=_SERIES)),
        patch("app.fundamentals.price_fallback._yf_price", return_value=100.0),
    ):
        resp = _client(price_cache=InMemoryPriceCache()).get(
            "/fundamentals/NVDA/metrics?metrics=pe"
        )
    body = resp.json()
    assert body["price_used"] == 100.0
    assert body["metrics"]["pe"] == 20.0


def test_metrics_uses_live_price():
    cache = InMemoryPriceCache()
    cache.update("NVDA", 100.0, 1)
    with patch("app.fundamentals.router._load_series", AsyncMock(return_value=_SERIES)):
        resp = _client(price_cache=cache).get("/fundamentals/NVDA/metrics?metrics=pe")
    body = resp.json()
    assert body["price_used"] == 100.0
    assert body["metrics"]["pe"] == 20.0  # 100 / eps 5


def test_metrics_unknown_name_422():
    with patch("app.fundamentals.router._load_series", AsyncMock(return_value=_SERIES)):
        resp = _client().get("/fundamentals/NVDA/metrics?metrics=bogus_only")
    assert resp.status_code == 422


def test_price_503_when_no_tick_and_rest_fails():
    with patch("app.fundamentals.price_fallback._yf_price", return_value=None):
        resp = _client(price_cache=InMemoryPriceCache()).get("/fundamentals/NVDA/price")
    assert resp.status_code == 503


def test_price_rest_fallback_when_no_tick():
    with patch("app.fundamentals.price_fallback._yf_price", return_value=77.0):
        resp = _client(price_cache=InMemoryPriceCache()).get("/fundamentals/NVDA/price")
    assert resp.status_code == 200
    body = resp.json()
    assert body["price"] == 77.0
    assert body["stale"] is False  # a REST quote is fresh


def test_price_ok_with_tick():
    cache = InMemoryPriceCache()
    cache.update("NVDA", 123.45, 1700000000000)
    resp = _client(price_cache=cache).get("/fundamentals/NVDA/price")
    assert resp.status_code == 200
    body = resp.json()
    assert body["price"] == 123.45
    assert body["stale"] is True  # old timestamp


# ── Tracklist ─────────────────────────────────────────────────────────────────


def _client_conn(conn: MagicMock) -> TestClient:
    from app.main import app

    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    app.state.pool = pool
    app.state.price_cache = None
    return TestClient(app, raise_server_exceptions=False)


def test_list_tracked():
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"symbol": "NVDA", "name": "NVIDIA", "gics_sector": "Tech", "market_cap_tier": "mega"}
        ]
    )
    resp = _client_conn(conn).get("/fundamentals/tracked")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["symbol"] == "NVDA"
    assert body[0]["sector"] == "Tech"


def test_add_tracked_ok():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "symbol": "AAPL",
            "name": "Apple",
            "gics_sector": "Tech",
            "market_cap_tier": "mega",
        }
    )
    with patch("app.fundamentals.router.ingest_statements", AsyncMock()):
        resp = _client_conn(conn).post("/fundamentals/tracked/AAPL")
    assert resp.status_code == 201
    assert resp.json()["symbol"] == "AAPL"


def test_add_tracked_unknown_symbol_404():
    conn = MagicMock()
    with patch(
        "app.fundamentals.router.ingest_statements",
        AsyncMock(side_effect=ValueError("No data found for symbol: ZZZZ")),
    ):
        resp = _client_conn(conn).post("/fundamentals/tracked/ZZZZ")
    assert resp.status_code == 404


def test_remove_tracked_204():
    conn = MagicMock()
    conn.execute = AsyncMock()
    resp = _client_conn(conn).request("DELETE", "/fundamentals/tracked/NVDA")
    assert resp.status_code == 204
