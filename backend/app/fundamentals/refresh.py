"""
Freshness for stored statements: lazy TTL (read path) + earnings poller.

- `ensure_fresh`: stale-while-revalidate. Cold reads block-and-fetch; warm-stale
  reads return immediately and refresh in the background (deduped per symbol).
- `poll_earnings_watch`: drains the `earnings_watch` queue — re-ingests each
  pending ticker until its NEW quarter appears (period_end advanced), then marks
  it done; ages out at T+2 trading days (real NYSE calendar).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
from app.fundamentals.ingest import ingest_statements
from app.fundamentals.market_calendar import add_trading_days

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")
_IN_FLIGHT: set[str] = set()


def _ttl_days(tracked: bool) -> int:
    key = "FUNDAMENTALS_TTL_TRACKED_DAYS" if tracked else "FUNDAMENTALS_TTL_ADHOC_DAYS"
    return int(os.getenv(key, "30" if tracked else "7"))


def _ageout_trading_days() -> int:
    return int(os.getenv("EARNINGS_AGEOUT_TRADING_DAYS", "2"))


async def _max_fetched_at(conn: asyncpg.Connection, symbol: str) -> datetime | None:
    val: datetime | None = await conn.fetchval(
        "SELECT MAX(fs.fetched_at) FROM financial_statements fs "
        "JOIN equities e ON fs.equity_id = e.id WHERE e.symbol = $1",
        symbol,
    )
    return val


async def _max_period_end(conn: asyncpg.Connection, symbol: str) -> date | None:
    val: date | None = await conn.fetchval(
        "SELECT MAX(fs.period_end) FROM financial_statements fs "
        "JOIN equities e ON fs.equity_id = e.id WHERE e.symbol = $1",
        symbol,
    )
    return val


async def _bg_refresh(pool: asyncpg.Pool, symbol: str) -> None:
    try:
        async with pool.acquire() as conn:
            await ingest_statements(symbol, conn)
    except Exception as exc:  # noqa: BLE001 — background; never breaks the served read
        logger.warning("[fundamentals] background refresh failed for %s: %s", symbol, exc)
    finally:
        _IN_FLIGHT.discard(symbol)


def _schedule_bg_refresh(pool: asyncpg.Pool, symbol: str) -> None:
    if symbol in _IN_FLIGHT:
        return
    _IN_FLIGHT.add(symbol)
    asyncio.create_task(_bg_refresh(pool, symbol))


async def ensure_fresh(pool: asyncpg.Pool, symbol: str, *, tracked: bool) -> None:
    """Cold → block-and-fetch. Warm-but-stale → serve now + refresh in background."""
    symbol = symbol.upper()
    async with pool.acquire() as conn:
        last = await _max_fetched_at(conn, symbol)
        if last is None:
            await ingest_statements(symbol, conn)  # cold start — block
            return
    if datetime.now(UTC) - last > timedelta(days=_ttl_days(tracked)):
        _schedule_bg_refresh(pool, symbol)


async def poll_earnings_watch(pool: asyncpg.Pool) -> dict[str, int]:
    """One poll cycle over pending earnings_watch rows. Returns status counts."""
    today = datetime.now(_ET).date()
    counts = {"done": 0, "aged_out": 0, "pending": 0}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, symbol, earnings_date, expected_period_end "
            "FROM earnings_watch WHERE status = 'pending'"
        )
    for row in rows:
        symbol = row["symbol"]
        try:
            async with pool.acquire() as conn:
                await ingest_statements(symbol, conn)
                max_pe = await _max_period_end(conn, symbol)
                expected = row["expected_period_end"]
                if expected is not None and max_pe is not None and max_pe >= expected:
                    await conn.execute(
                        "UPDATE earnings_watch SET status='done', resolved_at=NOW(), "
                        "last_polled_at=NOW() WHERE id=$1",
                        row["id"],
                    )
                    counts["done"] += 1
                elif add_trading_days(row["earnings_date"], _ageout_trading_days()) < today:
                    await conn.execute(
                        "UPDATE earnings_watch SET status='aged_out', resolved_at=NOW(), "
                        "last_polled_at=NOW() WHERE id=$1",
                        row["id"],
                    )
                    counts["aged_out"] += 1
                    logger.warning(
                        "[fundamentals] earnings watch aged out: %s (earnings %s, expected %s)",
                        symbol,
                        row["earnings_date"],
                        expected,
                    )
                else:
                    await conn.execute(
                        "UPDATE earnings_watch SET attempts=attempts+1, last_polled_at=NOW() "
                        "WHERE id=$1",
                        row["id"],
                    )
                    counts["pending"] += 1
        except Exception as exc:  # noqa: BLE001 — keep draining the rest of the queue
            logger.warning("[fundamentals] poll failed for %s: %s", symbol, exc)
            counts["pending"] += 1
    return counts


async def pending_watch_count(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM earnings_watch WHERE status='pending'")
    return int(val or 0)
