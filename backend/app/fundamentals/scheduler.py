"""
In-process scheduler for the fundamentals refresh layer.

Mirrors the Finnhub websocket task: an asyncio loop started in the app lifespan.
- Once per day: sync the earnings calendar + seed the watch queue.
- Every EARNINGS_POLL_MINUTES, inside EARNINGS_POLL_WINDOW (ET): poll the watch
  queue — but only if there is pending work (idle otherwise; not wasteful).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import asyncpg
from app.fundamentals.calendar import seed_watch, sync_earnings_calendar
from app.fundamentals.refresh import pending_watch_count, poll_earnings_watch

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")


def _poll_minutes() -> int:
    return int(os.getenv("EARNINGS_POLL_MINUTES", "30"))


def _window() -> tuple[time, time]:
    raw = os.getenv("EARNINGS_POLL_WINDOW", "06:00-22:00")
    try:
        start_s, end_s = raw.split("-")
        sh, sm = (int(x) for x in start_s.split(":"))
        eh, em = (int(x) for x in end_s.split(":"))
        return time(sh, sm), time(eh, em)
    except Exception:  # noqa: BLE001
        return time(6, 0), time(22, 0)


def _in_window(now_et: datetime) -> bool:
    start, end = _window()
    return start <= now_et.time() <= end


class FundamentalsScheduler:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._stopping = False
        self._last_calendar_sync: date | None = None

    async def stop(self) -> None:
        self._stopping = True

    async def _daily_calendar_sync(self, today: date) -> None:
        if self._last_calendar_sync == today:
            return
        try:
            async with self._pool.acquire() as conn:
                written = await sync_earnings_calendar(conn)
                seeded = await seed_watch(conn)
            self._last_calendar_sync = today
            logger.info(
                "[fundamentals] calendar sync: %d entries, %d watch seeded", written, seeded
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[fundamentals] calendar sync failed: %s", exc)

    async def run(self) -> None:
        poll_seconds = _poll_minutes() * 60
        while not self._stopping:
            try:
                now_et = datetime.now(_ET)
                await self._daily_calendar_sync(now_et.date())
                if _in_window(now_et) and await pending_watch_count(self._pool) > 0:
                    counts = await poll_earnings_watch(self._pool)
                    logger.info("[fundamentals] earnings poll: %s", counts)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fundamentals] scheduler tick error: %s", exc)
            # Sleep in short slices so stop() is responsive.
            for _ in range(poll_seconds):
                if self._stopping:
                    return
                await asyncio.sleep(1)
