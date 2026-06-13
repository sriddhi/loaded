"""DB-layer tests: holdings rebuild + tx mutations (mocked asyncpg)."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.portfolio import db as pdb  # noqa: E402


def _conn(tx_rows: list[dict]) -> MagicMock:
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=tx_rows)
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    conn.fetchrow = AsyncMock()
    return conn


def _buy(i: int, qty: str, price: int, day: int = 2) -> dict:
    return {
        "id": i,
        "tx_type": "buy",
        "symbol": "AAPL",
        "qty": Decimal(qty),
        "price_cents": price,
        "fees_cents": 0,
        "amount_cents": -int(Decimal(qty) * price),
        "trade_date": date(2026, 1, day),
    }


def test_cents_dollars_roundtrip():
    assert pdb.cents(123.45) == 12_345
    assert pdb.dollars(12_345) == 123.45
    assert pdb.dollars(None) == 0


@pytest.mark.asyncio
async def test_rebuild_holdings_writes_derived_rows():
    deposit = {
        "id": 1,
        "tx_type": "deposit",
        "symbol": None,
        "qty": None,
        "price_cents": None,
        "fees_cents": 0,
        "amount_cents": 1_000_000,
        "trade_date": date(2026, 1, 1),
    }
    conn = _conn([deposit, _buy(2, "10", 10_000)])
    await pdb.rebuild_holdings(conn, 7)
    conn.execute.assert_any_await("DELETE FROM portfolio_holdings WHERE portfolio_id = $1", 7)
    rows = conn.executemany.await_args.args[1]
    assert rows[0][1] == "AAPL" and rows[0][3] == 10_000  # avg cost cents
    # cash updated: 1_000_000 − 100_000
    update_call = conn.execute.await_args_list[-1]
    assert update_call.args[2] == 900_000


@pytest.mark.asyncio
async def test_insert_transaction_rejects_oversell():
    conn = _conn([_buy(1, "2", 10_000)])
    with pytest.raises(ValueError, match="oversell"):
        await pdb.insert_transaction(
            conn,
            7,
            tx_type="sell",
            symbol="AAPL",
            qty=Decimal("5"),
            price_cents=11_000,
            fees_cents=0,
            gross_cents=0,
            trade_date=date(2026, 1, 3),
            note=None,
        )
    conn.fetchrow.assert_not_awaited()  # nothing inserted


@pytest.mark.asyncio
async def test_delete_transaction_not_found_and_revalidation():
    conn = _conn([_buy(1, "2", 10_000)])
    assert await pdb.delete_transaction(conn, 7, tx_id=99) is False
    # deleting the only buy that backs a later sell must raise
    sell = {
        "id": 2,
        "tx_type": "sell",
        "symbol": "AAPL",
        "qty": Decimal("1"),
        "price_cents": 12_000,
        "fees_cents": 0,
        "amount_cents": 12_000,
        "trade_date": date(2026, 1, 4),
    }
    conn2 = _conn([_buy(1, "2", 10_000), sell])
    with pytest.raises(ValueError):
        await pdb.delete_transaction(conn2, 7, tx_id=1)
