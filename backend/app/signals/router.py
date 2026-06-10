"""FastAPI router for the SPY signals module (prefix /signals, JWT-protected)."""

from __future__ import annotations

from typing import Any

import asyncpg
from app.signals.job import get_history, get_latest, tick_once
from app.signals.models import HorizonSignal, SpySignal, SpySignalHistory
from fastapi import APIRouter, HTTPException, Query, Request, status

router = APIRouter(prefix="/signals", tags=["signals"])


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _to_model(d: dict[str, Any]) -> SpySignal:
    return SpySignal(
        ts=d["ts"],
        price=d["price"],
        signals=[HorizonSignal(**s) for s in d["signals"]],
    )


@router.get("/spy/latest", response_model=SpySignal)
async def latest(request: Request) -> SpySignal:
    async with _pool(request).acquire() as conn:
        row = await get_latest(conn)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No signals yet — the job hasn't produced one (markets closed / no key).",
        )
    return _to_model(row)


@router.get("/spy/history", response_model=SpySignalHistory)
async def history(request: Request, limit: int = Query(60, ge=1, le=500)) -> SpySignalHistory:
    async with _pool(request).acquire() as conn:
        rows = await get_history(conn, limit)
    return SpySignalHistory(signals=[_to_model(r) for r in rows])


@router.post("/spy/run", response_model=SpySignal)
async def run_now(request: Request) -> SpySignal:
    """Force one signal cycle now (manual trigger for testing/demo)."""
    result = await tick_once(_pool(request))
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SPY price unavailable (Finnhub key missing or quote failed).",
        )
    return _to_model(result)
