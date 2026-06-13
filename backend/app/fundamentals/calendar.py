"""
Earnings-calendar sync (Finnhub free `/calendar/earnings`) + watch seeding.

The calendar gives us *when* a tracked ticker reports; the poller then watches for
its statements to land in yfinance. `expected_period_end` is the quarter the
filing should cover (the poller's done-signal target).
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import httpx

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")
FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/earnings"

_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _quarter_end(fiscal_quarter: int | None, fiscal_year: int | None) -> date | None:
    """Calendar quarter-end for (quarter, year). Best-effort detection target."""
    if not fiscal_quarter or not fiscal_year or fiscal_quarter not in _QUARTER_END:
        return None
    month, day = _QUARTER_END[fiscal_quarter]
    return date(fiscal_year, month, day)


async def sync_earnings_calendar(conn: asyncpg.Connection, days_ahead: int = 14) -> int:
    """Pull Finnhub earnings calendar for tracked symbols; upsert. Returns rows written."""
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        logger.info("[fundamentals] FINNHUB_API_KEY not set — earnings calendar sync skipped")
        return 0

    today = datetime.now(_ET).date()
    frm = (today - timedelta(days=3)).isoformat()
    to = (today + timedelta(days=days_ahead)).isoformat()

    tracked = {
        r["symbol"] for r in await conn.fetch("SELECT symbol FROM equities WHERE is_tracked = TRUE")
    }
    if not tracked:
        return 0

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                FINNHUB_CALENDAR_URL,
                params={"from": frm, "to": to},
                headers={"X-Finnhub-Token": key},
            )
        if resp.status_code != 200:
            logger.warning("[fundamentals] earnings calendar HTTP %s", resp.status_code)
            return 0
        entries = resp.json().get("earningsCalendar", []) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fundamentals] earnings calendar fetch failed: %s", exc)
        return 0

    written = 0
    for e in entries:
        symbol = str(e.get("symbol", "")).upper()
        d = e.get("date")
        if symbol not in tracked or not d:
            continue
        quarter, year = e.get("quarter"), e.get("year")
        await conn.execute(
            """
            INSERT INTO earnings_calendar
                (symbol, earnings_date, hour, fiscal_quarter, fiscal_year, expected_period_end)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (symbol, earnings_date) DO UPDATE SET
                hour = EXCLUDED.hour,
                fiscal_quarter = EXCLUDED.fiscal_quarter,
                fiscal_year = EXCLUDED.fiscal_year,
                expected_period_end = EXCLUDED.expected_period_end,
                fetched_at = NOW()
            """,
            symbol,
            date.fromisoformat(str(d)),
            e.get("hour"),
            quarter,
            year,
            _quarter_end(quarter, year),
        )
        written += 1
    return written


async def seed_watch(conn: asyncpg.Connection) -> int:
    """Create pending watch rows for past/today calendar entries not yet resolved."""
    val = await conn.fetchval(
        """
        WITH inserted AS (
            INSERT INTO earnings_watch (symbol, earnings_date, expected_period_end)
            SELECT ec.symbol, ec.earnings_date, ec.expected_period_end
            FROM earnings_calendar ec
            WHERE ec.earnings_date <= CURRENT_DATE
            ON CONFLICT (symbol, earnings_date) DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*) FROM inserted
        """
    )
    return int(val or 0)
