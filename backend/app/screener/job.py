"""
Nightly screener orchestration + scheduler.

Phases (each fault-isolated — scoring runs on cached data if ingest fails):
  1. universe refresh   2. stale-statement ingest (budgeted)
  3. batched closes     4. pure scoring pass + rank update
A module-level lock makes the nightly tick and POST /screener/run mutually
exclusive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
from app.ops.metrics import track_job
from app.screener.data import (
    closes_map,
    refresh_closes,
    stale_statement_symbols,
)
from app.screener.scoring import SymbolInputs, score_symbol
from app.screener.universe import refresh_universe, universe_symbols

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
SCREENER_LOCK = asyncio.Lock()
LAST_RUN: dict[str, Any] = {"at": None, "scored": 0}


def _ingest_budget() -> int:
    try:
        return int(os.getenv("SCREENER_INGEST_BUDGET", "120"))
    except ValueError:
        return 120


async def _ingest_stale(pool: asyncpg.Pool, symbols: list[str], budget: int) -> int:
    # fundamentals.ingest writes financial_statements (the table the scorers
    # read); agents.ingest also refreshes analyst_estimates (its statement
    # write targets the legacy `fundamentals` table, harmless duplication).
    from app.agents.ingest import ingest_fundamentals
    from app.fundamentals.ingest import ingest_statements

    stale = await stale_statement_symbols(pool, symbols)
    todo = stale[:budget]
    if len(stale) > budget:
        logger.info(
            "[screener] %d stale statements, ingesting %d (budget) — rest next night",
            len(stale),
            budget,
        )
    sem = asyncio.Semaphore(2)
    done = 0

    async def one(sym: str) -> None:
        nonlocal done
        async with sem:
            try:
                async with pool.acquire() as conn:
                    result: dict[str, Any] = await ingest_statements(sym, conn)
                    await ingest_fundamentals(sym, conn)  # analyst_estimates
                if result.get("periods_written"):
                    done += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("[screener] ingest failed for %s: %r", sym, exc)
            await asyncio.sleep(1.0 + random.random())  # noqa: S311 — politeness jitter

    await asyncio.gather(*(one(s) for s in todo))
    return done


async def _load_inputs(pool: asyncpg.Pool, members: list[dict[str, Any]]) -> list[SymbolInputs]:
    symbols = [m["symbol"] for m in members]
    closes = await closes_map(pool, symbols)
    stmt_rows = await pool.fetch(
        """
        SELECT e.symbol, fs.*
        FROM financial_statements fs
        JOIN equities e ON e.id = fs.equity_id
        WHERE e.symbol = ANY($1) AND fs.period_type = 'annual'
        ORDER BY e.symbol, fs.period_end DESC
        """,
        symbols,
    )
    stmts: dict[str, list[dict[str, Any]]] = {}
    for r in stmt_rows:
        lst = stmts.setdefault(r["symbol"], [])
        if len(lst) < 4:
            row = dict(r)
            row["period_type"] = "annual"
            lst.append(row)
    analyst_rows = await pool.fetch(
        """
        SELECT e.symbol, a.target_price_mean, a.recommendation, a.num_analysts
        FROM analyst_estimates a JOIN equities e ON e.id = a.equity_id
        WHERE e.symbol = ANY($1)
        """,
        symbols,
    )
    analysts = {r["symbol"]: dict(r) for r in analyst_rows}
    fired_rows = await pool.fetch("SELECT alert_id FROM macro_alert_state WHERE fired")
    fired = {r["alert_id"] for r in fired_rows}

    # trailing P/E per symbol → sector medians
    pe_by_sector: dict[str, list[float]] = {}
    prices: dict[str, float] = {s: c[-1] for s, c in closes.items() if c}
    for m in members:
        sym, sector = m["symbol"], m.get("sector")
        px = prices.get(sym)
        rows = stmts.get(sym) or []
        eps = rows[0].get("eps_diluted") if rows else None
        if px and eps and sector:
            try:
                e = float(eps)
                if e > 0:
                    pe_by_sector.setdefault(sector, []).append(px / e)
            except (TypeError, ValueError):
                pass
    sector_median: dict[str, float] = {}
    for sector, pes in pe_by_sector.items():
        pes.sort()
        sector_median[sector] = pes[len(pes) // 2]

    inputs: list[SymbolInputs] = []
    for m in members:
        sym = m["symbol"]
        inputs.append(
            SymbolInputs(
                symbol=sym,
                sector=m.get("sector"),
                statements=stmts.get(sym, []),
                analyst=analysts.get(sym),
                closes=closes.get(sym, []),
                price=prices.get(sym),
                fired_alert_ids=fired,
                sector_pe_median=sector_median.get(m.get("sector") or ""),
            )
        )
    return inputs


async def _persist_scores(pool: asyncpg.Pool, results: list[dict[str, Any]]) -> int:
    today = datetime.now(UTC).date()
    id_rows = await pool.fetch(
        "SELECT id, symbol FROM equities WHERE symbol = ANY($1)",
        [r["symbol"] for r in results],
    )
    ids = {r["symbol"]: int(r["id"]) for r in id_rows}
    rows = []
    for r in results:
        eid = ids.get(r["symbol"])
        if eid is None:
            continue
        p = r["pillars"]
        rows.append(
            (
                eid,
                today,
                r["composite"],
                p["value"],
                p["quality"],
                p["growth"],
                p["momentum"],
                p["analyst"],
                p["macro_fit"],
                r["coverage"],
                r["candidate"],
                r["price_cents"],
                json.dumps(r["reasons"]),
                json.dumps(r["inputs"]),
            )
        )
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO screener_scores (equity_id, score_date, composite, value_score,
                quality_score, growth_score, momentum_score, analyst_score,
                macro_fit_score, coverage, candidate, price_cents, reasons, inputs)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (equity_id, score_date) DO UPDATE SET
                composite = EXCLUDED.composite, value_score = EXCLUDED.value_score,
                quality_score = EXCLUDED.quality_score, growth_score = EXCLUDED.growth_score,
                momentum_score = EXCLUDED.momentum_score, analyst_score = EXCLUDED.analyst_score,
                macro_fit_score = EXCLUDED.macro_fit_score, coverage = EXCLUDED.coverage,
                candidate = EXCLUDED.candidate, price_cents = EXCLUDED.price_cents,
                reasons = EXCLUDED.reasons, inputs = EXCLUDED.inputs
            """,
            rows,
        )
        await conn.execute(
            """
            UPDATE screener_scores s SET rank = r.rnk
            FROM (SELECT id, rank() OVER (ORDER BY composite DESC NULLS LAST, equity_id) rnk
                  FROM screener_scores WHERE score_date = $1) r
            WHERE s.id = r.id
            """,
            today,
        )
    return len(rows)


async def run_screener(pool: asyncpg.Pool, *, ingest_budget: int | None = None) -> dict[str, Any]:
    """Full nightly pass. Caller must hold SCREENER_LOCK."""
    budget = ingest_budget if ingest_budget is not None else _ingest_budget()
    summary: dict[str, Any] = {}
    try:
        summary["universe"] = await refresh_universe(pool)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screener] universe refresh failed: %r", exc)
    members = await universe_symbols(pool)
    symbols = [m["symbol"] for m in members]
    try:
        summary["ingested"] = await _ingest_stale(pool, symbols, budget)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screener] ingest phase failed: %r", exc)
    try:
        written = await refresh_closes(pool, symbols)
        summary["closes_symbols"] = len(written)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screener] closes phase failed: %r", exc)
    inputs = await _load_inputs(pool, members)
    results = [score_symbol(i) for i in inputs]
    summary["scored"] = await _persist_scores(pool, results)
    LAST_RUN["at"] = datetime.now(UTC).isoformat()
    LAST_RUN["scored"] = summary["scored"]
    logger.info("[screener] nightly run complete: %s", summary)
    return summary


async def _scored_today(pool: asyncpg.Pool) -> bool:
    today = datetime.now(UTC).date()
    n = await pool.fetchval("SELECT count(*) FROM screener_scores WHERE score_date = $1", today)
    return bool(n)


class ScreenerScheduler:
    """Nightly tick: weekday, after 16:10 ET, once per day."""

    def __init__(self, pool: asyncpg.Pool, check_interval_seconds: int = 600) -> None:
        self._pool = pool
        self._interval = check_interval_seconds
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True

    def _due(self, now_et: datetime) -> bool:
        if now_et.weekday() >= 5:
            return False
        return now_et.hour > 16 or (now_et.hour == 16 and now_et.minute >= 10)

    async def run(self) -> None:
        logger.info("[screener] scheduler started (nightly after close)")
        while not self._stopping:
            try:
                now_et = datetime.now(ET)
                if self._due(now_et) and not await _scored_today(self._pool):
                    async with SCREENER_LOCK:
                        with track_job("screener_nightly", "backend"):
                            await run_screener(self._pool)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[screener] scheduler error: %r", exc)
            for _ in range(self._interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)
