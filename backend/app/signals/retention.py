"""
Signal retention — a once-daily cleanup that runs after the US market closes and
deletes signal rows (and therefore their backtest verdicts / hit-rate, which live
on the same rows) older than a week.

Keeps `spy_signals` bounded: at ~1 row/minute × 3 symbols that's a few thousand
rows/day, so a 7-day window is plenty for the UI history + hit-rate while never
growing without limit.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import asyncpg
from app.ops.metrics import track_job

logger = logging.getLogger(__name__)

RETENTION_DAYS = 7


async def purge_old(pool: asyncpg.Pool, days: int = RETENTION_DAYS) -> int:
    """Delete signal rows older than `days`. Returns the number removed.

    Backtest verdicts (res_*) and the hit-rate are derived from these same rows,
    so deleting the rows cleans the hit-rate too — no separate step needed.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM spy_signals WHERE ts < NOW() - make_interval(days => $1)", days
        )
    # asyncpg returns e.g. "DELETE 1234"
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


def _market_close_passed(now_utc: datetime) -> bool:
    """True if the US market has closed for today (and today is a trading day).

    Uses the real NYSE calendar; the cleanup is meant to run *after* the close.
    """
    try:
        import exchange_calendars as xcals

        cal = xcals.get_calendar("XNYS")
        session = now_utc.date().isoformat()
        if not cal.is_session(session):
            return False
        close = cal.session_close(session)  # tz-aware UTC
        return bool(now_utc >= close.to_pydatetime())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[retention] calendar check failed (%s); using 21:00 UTC fallback", exc)
        # Fallback: NYSE closes 20:00–21:00 UTC depending on DST; 21:00 is safe.
        return now_utc.hour >= 21


class RetentionJob:
    """Wakes periodically; runs `purge_old` once per day after the market close."""

    def __init__(self, pool: asyncpg.Pool, check_interval_seconds: int = 600) -> None:
        self._pool = pool
        self._interval = check_interval_seconds
        self._stopping = False
        self._last_purge_date: str | None = None

    async def stop(self) -> None:
        self._stopping = True

    async def _maybe_purge(self, now_utc: datetime) -> int | None:
        today = now_utc.date().isoformat()
        if self._last_purge_date == today:
            return None  # already cleaned today
        if not _market_close_passed(now_utc):
            return None  # wait until after the close
        with track_job("signal_retention", "backend"):
            deleted = await purge_old(self._pool)
        self._last_purge_date = today
        logger.info("[retention] purged %d signal row(s) older than %dd", deleted, RETENTION_DAYS)
        return deleted

    async def run(self) -> None:
        logger.info("[retention] signal retention job started (daily, after market close)")
        while not self._stopping:
            try:
                await self._maybe_purge(datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[retention] purge error: %s", exc)
            for _ in range(self._interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)
