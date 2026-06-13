"""
Screener data pipeline: batched daily closes + statement freshness.

Closes come from chunked multi-ticker yf.download calls (~11 HTTP requests for
550 symbols, never per-symbol) and are persisted into market_bars '1d' so the
scoring pass, beta math and snapshots all read from the DB. Per-chunk failures
are logged and skipped — a bad chunk never aborts the night.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

ALWAYS_INCLUDE = ("SPY", "IGV", "SMH")  # macro technicals + beta benchmark
FIRST_RUN_LOOKBACK_D = 320
INCREMENTAL_LOOKBACK_D = 10


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _download_chunk(symbols: list[str], period_days: int) -> dict[str, list[dict[str, Any]]]:
    """Blocking yf.download for one chunk → {symbol: [{ts, open..volume}]}."""
    import pandas as pd
    import yfinance as yf

    out: dict[str, list[dict[str, Any]]] = {}
    df = yf.download(
        " ".join(symbols),
        period=f"{period_days}d",
        interval="1d",
        group_by="ticker",
        threads=False,
        progress=False,
        auto_adjust=True,
    )
    if df is None or df.empty:
        return out
    for sym in symbols:
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
        except KeyError:
            continue
        sub = sub.dropna(subset=["Close"])
        rows = []
        for ts, row in sub.iterrows():
            rows.append(
                {
                    "ts": ts.to_pydatetime().replace(tzinfo=UTC),
                    "open": float(row["Open"]) if not math.isnan(row["Open"]) else None,
                    "high": float(row["High"]) if not math.isnan(row["High"]) else None,
                    "low": float(row["Low"]) if not math.isnan(row["Low"]) else None,
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]) if not math.isnan(row["Volume"]) else 0,
                }
            )
        if rows:
            out[sym] = rows
    return out


async def _equity_ids(pool: asyncpg.Pool, symbols: list[str]) -> dict[str, int]:
    rows = await pool.fetch("SELECT id, symbol FROM equities WHERE symbol = ANY($1)", symbols)
    found = {r["symbol"]: int(r["id"]) for r in rows}
    missing = [s for s in symbols if s not in found]
    if missing:
        async with pool.acquire() as conn:
            for sym in missing:
                row = await conn.fetchrow(
                    "INSERT INTO equities (symbol, name) VALUES ($1, $1) "
                    "ON CONFLICT (symbol) DO UPDATE SET symbol = EXCLUDED.symbol RETURNING id",
                    sym,
                )
                assert row is not None
                found[sym] = int(row["id"])
    return found


async def _first_run_symbols(pool: asyncpg.Pool, ids: dict[str, int]) -> set[str]:
    rows = await pool.fetch(
        "SELECT DISTINCT equity_id FROM market_bars WHERE timeframe = '1d' AND equity_id = ANY($1)",
        list(ids.values()),
    )
    have = {int(r["equity_id"]) for r in rows}
    return {s for s, eid in ids.items() if eid not in have}


async def refresh_closes(
    pool: asyncpg.Pool, symbols: list[str], *, chunk_size: int = 50
) -> dict[str, int]:
    """Pull + upsert daily bars for symbols (∪ ALWAYS_INCLUDE). Returns rows/symbol."""
    universe = sorted({*symbols, *ALWAYS_INCLUDE})
    ids = await _equity_ids(pool, universe)
    first_run = await _first_run_symbols(pool, ids)
    written: dict[str, int] = {}
    for chunk in _chunks(universe, chunk_size):
        lookback = (
            FIRST_RUN_LOOKBACK_D if any(s in first_run for s in chunk) else INCREMENTAL_LOOKBACK_D
        )
        try:
            data = await asyncio.to_thread(_download_chunk, chunk, lookback)
        except Exception as exc:  # noqa: BLE001 — bad chunk never aborts the night
            logger.warning("[screener] closes chunk failed (%s…): %r", chunk[0], exc)
            continue
        rows: list[tuple[Any, ...]] = []
        for sym, bars in data.items():
            eid = ids.get(sym)
            if eid is None:
                continue
            written[sym] = len(bars)
            rows.extend(
                (b["ts"], eid, "1d", b["open"], b["high"], b["low"], b["close"], b["volume"])
                for b in bars
            )
        if rows:
            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO market_bars (time, equity_id, timeframe, open, high,
                                             low, close, volume)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (equity_id, timeframe, time) DO UPDATE
                      SET close = EXCLUDED.close, volume = EXCLUDED.volume,
                          open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low
                    """,
                    rows,
                )
    logger.info("[screener] closes refreshed for %d/%d symbols", len(written), len(universe))
    return written


async def stale_statement_symbols(
    pool: asyncpg.Pool, symbols: list[str], *, max_age_days: int = 30
) -> list[str]:
    """Symbols whose newest statement is older than the TTL (or absent), stalest first."""
    rows = await pool.fetch(
        """
        SELECT e.symbol, max(fs.fetched_at) AS newest
        FROM equities e
        LEFT JOIN financial_statements fs ON fs.equity_id = e.id
        WHERE e.symbol = ANY($1)
        GROUP BY e.symbol
        """,
        symbols,
    )
    now = datetime.now(UTC)
    stale: list[tuple[str, float]] = []
    for r in rows:
        newest = r["newest"]
        if newest is None:
            stale.append((r["symbol"], float("inf")))
        else:
            age = (now - newest).total_seconds() / 86_400
            if age > max_age_days:
                stale.append((r["symbol"], age))
    stale.sort(key=lambda t: -t[1])
    return [s for s, _ in stale]


async def closes_map(
    pool: asyncpg.Pool, symbols: list[str], *, days: int = 320
) -> dict[str, list[float]]:
    """Ascending daily closes per symbol from market_bars '1d'."""
    rows = await pool.fetch(
        """
        SELECT e.symbol, b.close
        FROM (
            SELECT equity_id, time, close,
                   row_number() OVER (PARTITION BY equity_id ORDER BY time DESC) AS rn
            FROM market_bars WHERE timeframe = '1d'
        ) b
        JOIN equities e ON e.id = b.equity_id
        WHERE e.symbol = ANY($1) AND b.rn <= $2
        ORDER BY e.symbol, b.time
        """,
        symbols,
        days,
    )
    out: dict[str, list[float]] = {}
    for r in rows:
        out.setdefault(r["symbol"], []).append(float(r["close"]))
    return out
