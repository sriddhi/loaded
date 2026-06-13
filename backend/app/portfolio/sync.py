"""
Alpaca PAPER account → synced portfolio (READ-ONLY).

Pulls positions + cash from the paper account and full-replaces the user's
single kind='alpaca_paper' portfolio inside one DB transaction. Never places,
modifies, or cancels orders — the only client calls are get_all_positions()
and get_account(). Synced portfolios carry no fabricated transactions; their
transaction list stays empty and mutation endpoints reject with 409.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

SYNCED_NAME = "Alpaca Paper"


class AlpacaUnavailableError(RuntimeError):
    """Credentials missing or the broker API failed."""


def _fetch_paper_state() -> tuple[list[Any], float]:
    """Blocking SDK calls — run via to_thread. Returns (positions, cash)."""
    from app.alpaca.client import get_trading_client

    client = get_trading_client(paper=True)
    positions = client.get_all_positions()
    account = client.get_account()
    cash = float(getattr(account, "cash", 0) or 0)  # TradeAccount | raw dict union
    return list(positions), cash


async def sync_alpaca_paper(pool: asyncpg.Pool, owner_id: int) -> dict[str, Any]:
    """Full-replace sync. Returns {portfolio_id, positions_synced, cash_cents}."""
    try:
        positions, cash = await asyncio.to_thread(_fetch_paper_state)
    except RuntimeError as exc:  # credentials missing (client factory raises)
        raise AlpacaUnavailableError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — SDK/network errors
        raise AlpacaUnavailableError(f"Alpaca API error: {exc}") from exc

    cash_cents = round(cash * 100)
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            INSERT INTO portfolios (owner_id, name, kind, cash_cents, last_synced_at)
            VALUES ($1, $2, 'alpaca_paper', $3, NOW())
            ON CONFLICT (owner_id, name) DO UPDATE
              SET cash_cents = EXCLUDED.cash_cents,
                  last_synced_at = NOW(),
                  updated_at = NOW()
            RETURNING id
            """,
            owner_id,
            SYNCED_NAME,
            cash_cents,
        )
        assert row is not None
        pid = int(row["id"])
        await conn.execute("DELETE FROM portfolio_holdings WHERE portfolio_id = $1", pid)
        rows = []
        for p in positions:
            qty = Decimal(str(p.qty))
            if qty <= 0:
                continue  # long-only books; short paper positions are skipped
            avg_cents = round(float(p.avg_entry_price) * 100)
            rows.append((pid, str(p.symbol).upper(), qty, avg_cents, round(qty * avg_cents)))
        if rows:
            await conn.executemany(
                "INSERT INTO portfolio_holdings (portfolio_id, symbol, qty, "
                "avg_cost_cents, cost_basis_cents) VALUES ($1, $2, $3, $4, $5)",
                rows,
            )
    logger.info("[portfolio] alpaca paper sync owner=%s positions=%d", owner_id, len(rows))
    return {"portfolio_id": pid, "positions_synced": len(rows), "cash_cents": cash_cents}
