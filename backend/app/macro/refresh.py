"""
Keep FRED series automatically up to date.

Each series has a frequency-based TTL (daily 6h, weekly 12h, monthly 24h). The
MacroScheduler ticks hourly and refreshes whatever is stale; refresh is
incremental (re-pulls a trailing window and upserts) and idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from app.macro.fred import DEFAULT_START, fetch_meta, fetch_observations
from app.macro.registry import SERIES, TTL_HOURS
from app.ops.metrics import track_job

logger = logging.getLogger(__name__)


def ttl_hours(code: str) -> int:
    hours: int = TTL_HOURS.get(SERIES.get(code, {}).get("freq", "m"), 24)
    return hours


async def series_stale(conn: asyncpg.Connection, code: str) -> bool:
    fetched_at: datetime | None = await conn.fetchval(
        "SELECT fetched_at FROM macro_series WHERE code = $1", code
    )
    if fetched_at is None:
        return True
    return datetime.now(UTC) - fetched_at > timedelta(hours=ttl_hours(code))


async def refresh_series(pool: asyncpg.Pool, code: str, *, full: bool = False) -> int:
    """Fetch + upsert observations for one series. Returns rows upserted."""
    info = SERIES.get(code, {})
    async with pool.acquire() as conn:
        last: Any = await conn.fetchval(
            "SELECT max(date) FROM macro_observations WHERE code = $1", code
        )
    # Incremental: re-pull a trailing 90-day window (covers revisions); full on first run.
    start = DEFAULT_START
    if not full and last is not None:
        start = (last - timedelta(days=90)).isoformat()

    obs = await fetch_observations(code, start=start)
    meta = await fetch_meta(code)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
                INSERT INTO macro_series (code, title, frequency, fetched_at, fred_updated_at)
                VALUES ($1, $2, $3, NOW(), $4)
                ON CONFLICT (code) DO UPDATE
                  SET fetched_at = NOW(),
                      title = EXCLUDED.title,
                      fred_updated_at = COALESCE(EXCLUDED.fred_updated_at,
                                                 macro_series.fred_updated_at)
                """,
            code,
            meta.get("title") or info.get("title", code),
            info.get("freq", "m"),
            meta.get("last_updated") or None,
        )
        if obs:
            await conn.executemany(
                """
                    INSERT INTO macro_observations (code, date, value)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (code, date) DO UPDATE SET value = EXCLUDED.value
                    """,
                [(code, d, v) for d, v in obs],
            )
    logger.info("[macro] refreshed %s: %d observations (from %s)", code, len(obs), start)
    return len(obs)


async def refresh_stale(pool: asyncpg.Pool, *, force: bool = False) -> dict[str, int]:
    """Refresh every registry series whose TTL elapsed (or all when force)."""
    out: dict[str, int] = {}
    sem = asyncio.Semaphore(4)  # be polite to FRED, but don't serialize 15 pulls

    async def one(code: str) -> None:
        try:
            async with sem:
                async with pool.acquire() as conn:
                    stale = await series_stale(conn, code)
                if force or stale:
                    out[code] = await refresh_series(pool, code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[macro] refresh failed for %s: %r", code, exc)

    await asyncio.gather(*(one(code) for code in SERIES))
    return out


async def load_series(pool: asyncpg.Pool, code: str, limit: int = 600) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT date, value FROM macro_observations WHERE code = $1 ORDER BY date DESC LIMIT $2",
        code,
        limit,
    )
    return [{"date": r["date"].isoformat(), "value": float(r["value"])} for r in reversed(rows)]


class MacroScheduler:
    """Hourly loop: refresh stale FRED series so sources track FRED updates."""

    def __init__(self, pool: asyncpg.Pool, check_interval_seconds: int = 3600) -> None:
        self._pool = pool
        self._interval = check_interval_seconds
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        logger.info("[macro] scheduler started (hourly staleness check)")
        while not self._stopping:
            try:
                with track_job("macro_fred_refresh", "backend"):
                    refreshed = await refresh_stale(self._pool)
                if refreshed:
                    logger.info("[macro] refreshed %d series", len(refreshed))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[macro] scheduler error: %s", exc)
            for _ in range(self._interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)
