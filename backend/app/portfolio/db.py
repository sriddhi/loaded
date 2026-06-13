"""
asyncpg helpers for the portfolio module.

Every query is owner-scoped: callers pass owner_id from the JWT and a missing
row means "not yours or not there" — the router turns that into 404 (no
existence leak). Holdings are a derived cache rebuilt inside the same DB
transaction as any transaction mutation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import asyncpg
from app.portfolio.math import amount_for, derive_holdings, validate_sequence


def cents(dollars: float) -> int:
    return round(dollars * 100)


def dollars(c: int | None) -> float:
    return (c or 0) / 100


async def get_portfolio(
    conn: asyncpg.Connection, portfolio_id: int, owner_id: int
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM portfolios WHERE id = $1 AND owner_id = $2", portfolio_id, owner_id
    )


async def list_portfolios(conn: asyncpg.Connection, owner_id: int) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = await conn.fetch(
        "SELECT * FROM portfolios WHERE owner_id = $1 ORDER BY created_at", owner_id
    )
    return rows


async def load_transactions(conn: asyncpg.Connection, portfolio_id: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT * FROM portfolio_transactions WHERE portfolio_id = $1 ORDER BY trade_date, id",
        portfolio_id,
    )
    return [dict(r) for r in rows]


async def load_holdings(conn: asyncpg.Connection, portfolio_id: int) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = await conn.fetch(
        "SELECT h.*, e.name AS equity_name, e.gics_sector AS sector "
        "FROM portfolio_holdings h "
        "LEFT JOIN equities e ON e.symbol = h.symbol "
        "WHERE h.portfolio_id = $1 AND h.qty > 0 ORDER BY h.symbol",
        portfolio_id,
    )
    return rows


async def rebuild_holdings(conn: asyncpg.Connection, portfolio_id: int) -> None:
    """Re-derive holdings + cash from the full transaction list (one DB tx)."""
    txs = await load_transactions(conn, portfolio_id)
    holdings, cash = validate_sequence(txs)
    await conn.execute("DELETE FROM portfolio_holdings WHERE portfolio_id = $1", portfolio_id)
    rows = [
        (
            portfolio_id,
            h["symbol"],
            h["qty"],
            h["avg_cost_cents"],
            h["cost_basis_cents"],
            h["realized_pnl_cents"],
            h["first_acquired"],
        )
        for h in holdings.values()
        if h["qty"] > 0 or h["realized_pnl_cents"] != 0
    ]
    if rows:
        await conn.executemany(
            "INSERT INTO portfolio_holdings (portfolio_id, symbol, qty, avg_cost_cents, "
            "cost_basis_cents, realized_pnl_cents, first_acquired) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            rows,
        )
    await conn.execute(
        "UPDATE portfolios SET cash_cents = $2, updated_at = NOW() WHERE id = $1",
        portfolio_id,
        cash,
    )


async def insert_transaction(
    conn: asyncpg.Connection,
    portfolio_id: int,
    *,
    tx_type: str,
    symbol: str | None,
    qty: Decimal | None,
    price_cents: int | None,
    fees_cents: int,
    gross_cents: int,
    trade_date: date,
    note: str | None,
    source: str = "manual",
) -> asyncpg.Record:
    """Validate the would-be sequence, insert, rebuild holdings. ValueError on bad."""
    existing = await load_transactions(conn, portfolio_id)
    amount = amount_for(tx_type, qty, price_cents, fees_cents, gross_cents)
    candidate = {
        "tx_type": tx_type,
        "symbol": symbol,
        "qty": qty,
        "price_cents": price_cents,
        "fees_cents": fees_cents,
        "amount_cents": amount,
        "trade_date": trade_date,
    }
    seq = sorted([*existing, candidate], key=lambda t: (t["trade_date"], t.get("id") or 10**12))
    validate_sequence(seq)  # raises ValueError (oversell/overdraw)
    row = await conn.fetchrow(
        "INSERT INTO portfolio_transactions (portfolio_id, symbol, tx_type, qty, "
        "price_cents, amount_cents, fees_cents, trade_date, note, source) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING *",
        portfolio_id,
        symbol,
        tx_type,
        qty,
        price_cents,
        amount,
        fees_cents,
        trade_date,
        note,
        source,
    )
    await rebuild_holdings(conn, portfolio_id)
    assert row is not None
    return row


async def delete_transaction(conn: asyncpg.Connection, portfolio_id: int, tx_id: int) -> bool:
    """Delete one tx if the remaining sequence still validates. ValueError if not."""
    existing = await load_transactions(conn, portfolio_id)
    remaining = [t for t in existing if t["id"] != tx_id]
    if len(remaining) == len(existing):
        return False
    validate_sequence(remaining)  # raises if removal implies negative position/cash
    await conn.execute(
        "DELETE FROM portfolio_transactions WHERE id = $1 AND portfolio_id = $2",
        tx_id,
        portfolio_id,
    )
    await rebuild_holdings(conn, portfolio_id)
    return True


__all__ = [
    "cents",
    "dollars",
    "get_portfolio",
    "list_portfolios",
    "load_transactions",
    "load_holdings",
    "rebuild_holdings",
    "insert_transaction",
    "delete_transaction",
    "derive_holdings",
]
