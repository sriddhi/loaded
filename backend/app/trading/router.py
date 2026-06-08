"""FastAPI router for the SPY 0DTE trading job."""

from __future__ import annotations

from app.trading.job import _build_status_response, trading_job
from app.trading.models import JobStatusResponse, TradeLogEntry
from app.trading.state import reset_state, state_lock, trading_state
from fastapi import APIRouter, Request

router = APIRouter(tags=["trading"])


def _status() -> JobStatusResponse:
    return JobStatusResponse(**_build_status_response())


@router.post("/start", response_model=JobStatusResponse)
async def start_job(request: Request) -> JobStatusResponse:
    """Start the trading job. Idempotent."""
    await trading_job.start()
    return _status()


@router.post("/stop", response_model=JobStatusResponse)
async def stop_job(request: Request) -> JobStatusResponse:
    """Stop the trading job gracefully."""
    await trading_job.stop()
    return _status()


@router.get("/status", response_model=JobStatusResponse)
async def get_status(request: Request) -> JobStatusResponse:
    """Current trading job state snapshot."""
    return _status()


@router.get("/log", response_model=list[TradeLogEntry])
async def get_log(request: Request) -> list[TradeLogEntry]:
    """Trade activity log (last 100 entries)."""
    async with state_lock:
        entries = list(trading_state.trade_log[-100:])
    return [TradeLogEntry(**e) for e in entries]


@router.post("/reset", response_model=JobStatusResponse)
async def reset_job(request: Request) -> JobStatusResponse:
    """Stop the job and clear all state. Ready for a new session."""
    await trading_job.stop()
    reset_state()
    return _status()
