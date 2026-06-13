"""
EOD portfolio snapshots — daily value history for performance charts.

Valuation prefers today's market_bars '1d' close (persisted by the screener
job); fallback chain per symbol: 1d bar → resolve_price → last snapshot's
detail price → avg cost (flagged carried=True in detail). Missed days are
gaps, never fabricated.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
from app.ops.metrics import track_job

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
SNAPSHOT_AFTER_H, SNAPSHOT_AFTER_M = 16, 15
DEADLINE_HOUR = 18  # snapshot even without today's SPY bar after this ET hour


async def _today_bar_closes(pool: asyncpg.Pool, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    rows = await pool.fetch(
        """
        SELECT e.symbol, b.close
        FROM market_bars b JOIN equities e ON e.id = b.equity_id
        WHERE b.timeframe = '1d' AND b.time::date = CURRENT_DATE
          AND e.symbol = ANY($1)
        """,
        symbols,
    )
    return {r["symbol"]: float(r["close"]) for r in rows}


async def _last_detail_prices(pool: asyncpg.Pool, portfolio_id: int) -> dict[str, float]:
    row = await pool.fetchrow(
        "SELECT detail FROM portfolio_snapshots WHERE portfolio_id = $1 "
        "ORDER BY snapshot_date DESC LIMIT 1",
        portfolio_id,
    )
    if row is None or row["detail"] is None:
        return {}
    detail = row["detail"] if isinstance(row["detail"], dict) else json.loads(row["detail"])
    out: dict[str, float] = {}
    for sym, d in detail.items():
        price = d.get("price")
        if price:
            out[sym] = float(price)
    return out


async def snapshot_portfolio(pool: asyncpg.Pool, portfolio_row: Any) -> dict[str, Any]:
    """Value one portfolio at EOD and upsert today's snapshot row."""
    from app.fundamentals.price_fallback import resolve_price

    pid = int(portfolio_row["id"])
    today = datetime.now(UTC).date()
    holdings = await pool.fetch(
        "SELECT symbol, qty, avg_cost_cents, cost_basis_cents, realized_pnl_cents "
        "FROM portfolio_holdings WHERE portfolio_id = $1 AND qty > 0",
        pid,
    )
    symbols = [r["symbol"] for r in holdings]
    bar_closes = await _today_bar_closes(pool, symbols)
    carry = await _last_detail_prices(pool, pid)

    equity_cents = 0
    unrealized_cents = 0
    realized_cents = 0
    detail: dict[str, Any] = {}
    for h in holdings:
        sym = h["symbol"]
        qty = float(h["qty"])
        realized_cents += int(h["realized_pnl_cents"])
        price = bar_closes.get(sym)
        source = "bar"
        if price is None:
            try:
                resolved: tuple[float, int, str] | None = await resolve_price(sym, None)
            except Exception:  # noqa: BLE001
                resolved = None
            if resolved is not None:
                price, source = float(resolved[0]), "live"
        if price is None and sym in carry:
            price, source = carry[sym], "carried"
        if price is None:
            price, source = int(h["avg_cost_cents"]) / 100, "cost"
        value_cents = round(qty * price * 100)
        equity_cents += value_cents
        unrealized_cents += value_cents - int(h["cost_basis_cents"])
        detail[sym] = {"qty": qty, "price": price, "value": value_cents / 100, "src": source}

    cash_cents = int(portfolio_row["cash_cents"])
    flow = await pool.fetchval(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM portfolio_transactions "
        "WHERE portfolio_id = $1 AND trade_date = $2 "
        "AND tx_type IN ('deposit', 'withdrawal')",
        pid,
        today,
    )
    await pool.execute(
        """
        INSERT INTO portfolio_snapshots (portfolio_id, snapshot_date, equity_value_cents,
            cash_cents, total_value_cents, net_flow_cents, realized_pnl_cents,
            unrealized_pnl_cents, holdings_count, detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (portfolio_id, snapshot_date) DO UPDATE SET
            equity_value_cents = EXCLUDED.equity_value_cents,
            cash_cents = EXCLUDED.cash_cents,
            total_value_cents = EXCLUDED.total_value_cents,
            net_flow_cents = EXCLUDED.net_flow_cents,
            realized_pnl_cents = EXCLUDED.realized_pnl_cents,
            unrealized_pnl_cents = EXCLUDED.unrealized_pnl_cents,
            holdings_count = EXCLUDED.holdings_count,
            detail = EXCLUDED.detail
        """,
        pid,
        today,
        equity_cents,
        cash_cents,
        equity_cents + cash_cents,
        int(flow or 0),
        realized_cents,
        unrealized_cents,
        len(holdings),
        json.dumps(detail),
    )
    return {"portfolio_id": pid, "total_value_cents": equity_cents + cash_cents}


async def snapshot_all(pool: asyncpg.Pool) -> int:
    """Snapshot every active portfolio missing today's row. Returns count."""
    rows = await pool.fetch(
        """
        SELECT p.* FROM portfolios p
        WHERE p.is_active AND NOT EXISTS (
            SELECT 1 FROM portfolio_snapshots s
            WHERE s.portfolio_id = p.id AND s.snapshot_date = CURRENT_DATE
        )
        """
    )
    done = 0
    for row in rows:
        try:
            await snapshot_portfolio(pool, row)
            done += 1
        except Exception as exc:  # noqa: BLE001 — one bad portfolio never stops the rest
            logger.warning("[portfolio] snapshot failed for %s: %r", row["id"], exc)
    if done:
        logger.info("[portfolio] snapshotted %d portfolios", done)
    return done


async def _spy_bar_today(pool: asyncpg.Pool) -> bool:
    n = await pool.fetchval(
        """
        SELECT count(*) FROM market_bars b JOIN equities e ON e.id = b.equity_id
        WHERE e.symbol = 'SPY' AND b.timeframe = '1d' AND b.time::date = CURRENT_DATE
        """
    )
    return bool(n)


class PortfolioSnapshotScheduler:
    """Daily EOD valuation of all active portfolios."""

    def __init__(self, pool: asyncpg.Pool, check_interval_seconds: int = 600) -> None:
        self._pool = pool
        self._interval = check_interval_seconds
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True

    def _due(self, now_et: datetime) -> bool:
        if now_et.weekday() >= 5:
            return False
        return now_et.hour > SNAPSHOT_AFTER_H or (
            now_et.hour == SNAPSHOT_AFTER_H and now_et.minute >= SNAPSHOT_AFTER_M
        )

    async def run(self) -> None:
        logger.info("[portfolio] snapshot scheduler started (EOD)")
        while not self._stopping:
            try:
                now_et = datetime.now(ET)
                # prefer post-screener closes; never deadlock past the deadline
                if self._due(now_et) and (
                    await _spy_bar_today(self._pool) or now_et.hour >= DEADLINE_HOUR
                ):
                    with track_job("portfolio_snapshots", "backend"):
                        await snapshot_all(self._pool)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[portfolio] snapshot scheduler error: %r", exc)
            for _ in range(self._interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)
