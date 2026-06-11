"""FastAPI router for the signals module (prefix /signals, JWT-protected).

Multi-symbol: SPY, MU, AVGO. The background job updates every symbol once a
minute, so there is no manual "run" endpoint — reads are always fresh.
"""

from __future__ import annotations

from typing import Any

import asyncpg
from app.signals.job import SYMBOLS, get_history, get_latest
from app.signals.models import HorizonSignal, SpySignal, SpySignalHistory
from fastapi import APIRouter, HTTPException, Query, Request, status

router = APIRouter(prefix="/signals", tags=["signals"])


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _norm_symbol(symbol: str) -> str:
    sym = symbol.upper()
    if sym not in SYMBOLS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown symbol '{symbol}'. Tracked: {', '.join(SYMBOLS)}.",
        )
    return sym


def _to_model(d: dict[str, Any]) -> SpySignal:
    return SpySignal(
        ts=d["ts"],
        symbol=d.get("symbol", "SPY"),
        price=d["price"],
        volume=int(d.get("volume", 0) or 0),
        osc=d.get("osc"),
        signals=[HorizonSignal(**s) for s in d["signals"]],
    )


@router.get("/symbols")
async def symbols() -> dict[str, list[str]]:
    """List the symbols the signal job tracks."""
    return {"symbols": SYMBOLS}


@router.get("/{symbol}/latest", response_model=SpySignal)
async def latest(request: Request, symbol: str) -> SpySignal:
    sym = _norm_symbol(symbol)
    async with _pool(request).acquire() as conn:
        row = await get_latest(conn, sym)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {sym} signal yet — the job hasn't produced one (markets closed?).",
        )
    return _to_model(row)


@router.get("/{symbol}/history", response_model=SpySignalHistory)
async def history(
    request: Request, symbol: str, limit: int = Query(60, ge=1, le=500)
) -> SpySignalHistory:
    sym = _norm_symbol(symbol)
    async with _pool(request).acquire() as conn:
        rows = await get_history(conn, sym, limit)
    return SpySignalHistory(signals=[_to_model(r) for r in rows])
