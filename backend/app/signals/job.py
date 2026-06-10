"""
Signal job: every minute, for each tracked symbol fetch the latest 1-minute
price + volume (yfinance), append to a DB-backed series, classify the next
5/10/20 min and 1 day, and store the result.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import asyncpg
from app.signals.engine import HORIZONS, compute_all

logger = logging.getLogger(__name__)

# Symbols the job tracks. SPY (the market), plus MU and AVGO.
SYMBOLS: list[str] = ["SPY", "MU", "AVGO"]

# Samples used for classification — enough context for the 1-day horizon as the
# series builds (~a full trading day of 1-min ticks), per symbol.
_PRICE_HISTORY = 400


def signals_enabled() -> bool:
    # yfinance needs no API key; the job runs whenever it's wired up.
    return os.getenv("SIGNALS_DISABLED", "").lower() not in ("1", "true", "yes")


def _interval_seconds() -> int:
    return int(os.getenv("SIGNAL_INTERVAL_SECONDS", "60"))


def _fetch_quote_sync(symbol: str) -> tuple[float, int] | None:
    """Blocking yfinance call: latest 1-minute (price, volume) for `symbol`."""
    import yfinance as yf

    try:
        hist = yf.Ticker(symbol).history(period="1d", interval="1m")
        if hist is None or hist.empty:
            return None
        last = hist.iloc[-1]
        price = float(last["Close"])
        volume = int(last["Volume"] or 0)
        if price <= 0:
            return None
        return price, volume
    except Exception as exc:  # noqa: BLE001
        logger.warning("[signals] quote fetch failed for %s: %s", symbol, exc)
        return None


async def fetch_quote(symbol: str) -> tuple[float, int] | None:
    """Async wrapper — runs the synchronous yfinance fetch in a thread."""
    return await asyncio.to_thread(_fetch_quote_sync, symbol)


async def _recent_series(
    conn: asyncpg.Connection, symbol: str, n: int
) -> tuple[list[float], list[float]]:
    rows = await conn.fetch(
        "SELECT price, volume FROM spy_signals WHERE symbol = $1 ORDER BY ts DESC LIMIT $2",
        symbol,
        n,
    )
    # rows are newest-first; return oldest-first for the engine.
    rows = list(reversed(rows))
    prices = [float(r["price"]) for r in rows]
    volumes = [float(r["volume"] or 0) for r in rows]
    return prices, volumes


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


async def tick_once(pool: asyncpg.Pool, symbol: str) -> dict[str, Any] | None:
    """Run one signal cycle for `symbol`. Returns the stored signal, or None."""
    quote = await fetch_quote(symbol)
    if quote is None:
        return None
    price, volume = quote
    async with pool.acquire() as conn:
        prices, volumes = await _recent_series(conn, symbol, _PRICE_HISTORY)
        prices.append(price)
        volumes.append(float(volume))
        r = compute_all(prices, volumes)
        ts = await conn.fetchval(
            """
            INSERT INTO spy_signals
                (symbol, price, volume,
                 sig_5m, conf_5m, reason_5m, sig_10m, conf_10m, reason_10m,
                 sig_20m, conf_20m, reason_20m, sig_1d, conf_1d, reason_1d)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING ts
            """,
            symbol,
            price,
            volume,
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
    return {
        "ts": ts,
        "symbol": symbol,
        "price": price,
        "volume": volume,
        "signals": _results_to_signals(r),
    }


async def tick_all(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    """Run one signal cycle for every tracked symbol. Skips ones with no quote."""
    out: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        try:
            result = await tick_once(pool, symbol)
            if result is not None:
                out.append(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[signals] tick error for %s: %s", symbol, exc)
    return out


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
        "symbol": row["symbol"],
        "price": float(row["price"]),
        "volume": int(row["volume"] or 0),
        "signals": [
            sig(5, "sig_5m", "conf_5m", "reason_5m"),
            sig(10, "sig_10m", "conf_10m", "reason_10m"),
            sig(20, "sig_20m", "conf_20m", "reason_20m"),
            sig(1440, "sig_1d", "conf_1d", "reason_1d"),
        ],
    }


async def get_latest(conn: asyncpg.Connection, symbol: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT * FROM spy_signals WHERE symbol = $1 ORDER BY ts DESC LIMIT 1", symbol
    )
    return _row_to_signal(row) if row else None


async def get_history(conn: asyncpg.Connection, symbol: str, limit: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT * FROM spy_signals WHERE symbol = $1 ORDER BY ts DESC LIMIT $2", symbol, limit
    )
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
        logger.info("[signals] signal job started (every %ds) for %s", interval, ", ".join(SYMBOLS))
        while not self._stopping:
            try:
                results = await tick_all(self._pool)
                for result in results:
                    five = result["signals"][0]
                    logger.info(
                        "[signals] %s %.2f vol=%s → 5m %s",
                        result["symbol"],
                        result["price"],
                        result["volume"],
                        five["label"],
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[signals] tick error: %s", exc)
            for _ in range(interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)
