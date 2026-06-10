"""FastAPI router for the ops/Tools dashboard (prefix /ops, JWT-protected)."""

from __future__ import annotations

from typing import Any

import asyncpg
from app.ops.metrics import METRICS
from app.signals.engine import HORIZONS
from app.signals.job import SYMBOLS
from fastapi import APIRouter, Request

router = APIRouter(prefix="/ops", tags=["ops"])

_RESCOLS = {1: "res_1m", 5: "res_5m", 10: "res_10m", 20: "res_20m", 1440: "res_1d"}


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


async def _signal_insights(conn: asyncpg.Connection) -> dict[str, Any]:
    """Per-symbol row counts + overall backtest hit-rate per horizon."""
    per_symbol: list[dict[str, Any]] = []
    for sym in SYMBOLS:
        row = await conn.fetchrow(
            "SELECT count(*) AS n, max(ts) AS last_ts, min(ts) AS first_ts "
            "FROM spy_signals WHERE symbol = $1",
            sym,
        )
        per_symbol.append(
            {
                "symbol": sym,
                "rows": int(row["n"]) if row else 0,
                "last_ts": row["last_ts"].isoformat() if row and row["last_ts"] else None,
                "oldest_ts": row["first_ts"].isoformat() if row and row["first_ts"] else None,
            }
        )

    hit_rate: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        col = _RESCOLS[horizon]
        row = await conn.fetchrow(
            f"SELECT count(*) FILTER (WHERE {col} = 'correct') AS hits, "
            f"count(*) FILTER (WHERE {col} IN ('correct','wrong')) AS total, "
            f"count(*) FILTER (WHERE {col} IS NULL) AS pending "
            f"FROM spy_signals"
        )
        hits = int(row["hits"]) if row else 0
        total = int(row["total"]) if row else 0
        hit_rate.append(
            {
                "horizon_min": horizon,
                "hits": hits,
                "total": total,
                "pending": int(row["pending"]) if row else 0,
                "accuracy": round(hits / total, 3) if total else None,
            }
        )
    return {"per_symbol": per_symbol, "hit_rate": hit_rate}


@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    """Everything the Tools tab needs: jobs, API metrics, and signal insights."""
    snap: dict[str, Any] = METRICS.snapshot()
    async with _pool(request).acquire() as conn:
        snap["insights"] = await _signal_insights(conn)
    return snap
