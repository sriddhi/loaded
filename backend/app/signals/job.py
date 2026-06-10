"""
SPY signal job: every minute, fetch the latest SPY price (Finnhub /quote), append
to a DB-backed price series, classify the next 5/10/20 min, and store the result.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import asyncpg
import httpx
from app.signals.engine import HORIZONS, compute_all

logger = logging.getLogger(__name__)

QUOTE_URL = "https://finnhub.io/api/v1/quote"
# Samples used for classification — enough context for the 1-day horizon as the
# series builds (~a full trading day of 1-min ticks).
_PRICE_HISTORY = 400


def signals_enabled() -> bool:
    return bool(os.getenv("FINNHUB_API_KEY"))


def _interval_seconds() -> int:
    return int(os.getenv("SIGNAL_INTERVAL_SECONDS", "60"))


async def fetch_spy_quote() -> float | None:
    """Latest SPY price via Finnhub /quote. Returns None on error or no price."""
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                QUOTE_URL, params={"symbol": "SPY"}, headers={"X-Finnhub-Token": key}
            )
        if resp.status_code != 200:
            return None
        price = float(resp.json().get("c") or 0.0)
        return price if price > 0 else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[signals] quote fetch failed: %s", exc)
        return None


async def _recent_prices(conn: asyncpg.Connection, n: int) -> list[float]:
    rows = await conn.fetch("SELECT price FROM spy_signals ORDER BY ts DESC LIMIT $1", n)
    # rows are newest-first; return oldest-first for the engine.
    return [float(r["price"]) for r in reversed(rows)]


def _results_to_signals(results: dict[int, tuple[str, float, str]]) -> list[dict[str, Any]]:
    return [
        {
            "horizon_min": h,
            "label": results[h][0],
            "confidence": results[h][1],
            "reason": results[h][2],
        }
        for h in HORIZONS
    ]


async def tick_once(pool: asyncpg.Pool) -> dict[str, Any] | None:
    """Run one signal cycle. Returns the stored signal, or None if no price."""
    price = await fetch_spy_quote()
    if price is None:
        return None
    async with pool.acquire() as conn:
        series = await _recent_prices(conn, _PRICE_HISTORY)
        series.append(price)
        r = compute_all(series)
        ts = await conn.fetchval(
            """
            INSERT INTO spy_signals
                (price, sig_5m, conf_5m, reason_5m, sig_10m, conf_10m, reason_10m,
                 sig_20m, conf_20m, reason_20m, sig_1d, conf_1d, reason_1d)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING ts
            """,
            price,
            r[5][0],
            r[5][1],
            r[5][2],
            r[10][0],
            r[10][1],
            r[10][2],
            r[20][0],
            r[20][1],
            r[20][2],
            r[1440][0],
            r[1440][1],
            r[1440][2],
        )
    return {"ts": ts, "price": price, "signals": _results_to_signals(r)}


# ── Query helpers (used by the router) ────────────────────────────────────────


def _row_to_signal(row: asyncpg.Record) -> dict[str, Any]:
    def sig(h: int, sk: str, ck: str, rk: str) -> dict[str, Any]:
        return {
            "horizon_min": h,
            "label": row[sk],
            "confidence": float(row[ck] or 0),
            "reason": row[rk] or "",
        }

    return {
        "ts": row["ts"],
        "price": float(row["price"]),
        "signals": [
            sig(5, "sig_5m", "conf_5m", "reason_5m"),
            sig(10, "sig_10m", "conf_10m", "reason_10m"),
            sig(20, "sig_20m", "conf_20m", "reason_20m"),
            sig(1440, "sig_1d", "conf_1d", "reason_1d"),
        ],
    }


async def get_latest(conn: asyncpg.Connection) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM spy_signals ORDER BY ts DESC LIMIT 1")
    return _row_to_signal(row) if row else None


async def get_history(conn: asyncpg.Connection, limit: int) -> list[dict[str, Any]]:
    rows = await conn.fetch("SELECT * FROM spy_signals ORDER BY ts DESC LIMIT $1", limit)
    return [_row_to_signal(r) for r in rows]


# ── Background job ────────────────────────────────────────────────────────────


class SpySignalJob:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        interval = _interval_seconds()
        logger.info("[signals] SPY signal job started (every %ds)", interval)
        while not self._stopping:
            try:
                result = await tick_once(self._pool)
                if result is not None:
                    five = result["signals"][0]
                    logger.info("[signals] SPY %.2f → 5m %s", result["price"], five["label"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[signals] tick error: %s", exc)
            for _ in range(interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)
