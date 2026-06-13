"""Alpaca paper sync: idempotent full-replace, read-only, cents discipline."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.portfolio.sync import AlpacaUnavailableError, sync_alpaca_paper  # noqa: E402


def _pool():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    conn.fetchrow = AsyncMock(return_value={"id": 42})
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool, conn


def _pos(symbol: str, qty: str, avg: float):
    return SimpleNamespace(symbol=symbol, qty=qty, avg_entry_price=avg)


@pytest.mark.asyncio
async def test_sync_full_replace_and_cents():
    pool, conn = _pool()
    positions = [_pos("AAPL", "10", 150.25), _pos("MSFT", "0", 100.0)]  # 0-qty skipped
    with patch(
        "app.portfolio.sync._fetch_paper_state", MagicMock(return_value=(positions, 1234.56))
    ):
        out = await sync_alpaca_paper(pool, owner_id=1)
    assert out == {"portfolio_id": 42, "positions_synced": 1, "cash_cents": 123_456}
    conn.execute.assert_any_await("DELETE FROM portfolio_holdings WHERE portfolio_id = $1", 42)
    rows = conn.executemany.await_args.args[1]
    assert rows[0][1] == "AAPL" and rows[0][3] == 15_025  # avg_entry → cents


@pytest.mark.asyncio
async def test_sync_idempotent_upsert_sql():
    pool, conn = _pool()
    with patch("app.portfolio.sync._fetch_paper_state", MagicMock(return_value=([], 0.0))):
        await sync_alpaca_paper(pool, owner_id=1)
        await sync_alpaca_paper(pool, owner_id=1)
    sql = conn.fetchrow.await_args.args[0]
    assert "ON CONFLICT (owner_id, name) DO UPDATE" in sql  # converges, no dups


@pytest.mark.asyncio
async def test_sync_missing_credentials_maps_to_unavailable():
    pool, _ = _pool()
    with (
        patch(
            "app.portfolio.sync._fetch_paper_state",
            MagicMock(side_effect=RuntimeError("Alpaca paper credentials not configured")),
        ),
        pytest.raises(AlpacaUnavailableError),
    ):
        await sync_alpaca_paper(pool, owner_id=1)


def test_sync_module_is_read_only():
    """The module must never import or call order-placing APIs."""
    import inspect

    import app.portfolio.sync as sync_mod

    src = inspect.getsource(sync_mod)
    for forbidden in ("submit_order", "close_position", "OrderRequest", "cancel_order"):
        assert forbidden not in src
