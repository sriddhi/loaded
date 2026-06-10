"""FastAPI router for the SPY 0DTE trading job."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
from app.auth.security import get_current_user
from app.trading import db as trading_db
from app.trading.job import _build_status_response, trading_job
from app.trading.models import (
    CreateJobRequest,
    EventRecord,
    JobRecord,
    JobStatusResponse,
    SessionRecord,
    StartJobResponse,
    TradeLogEntry,
)
from app.trading.state import reset_state, state_lock, trading_state
from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(tags=["trading"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _is_admin(user: Any) -> bool:
    if isinstance(user, dict):
        return user.get("role") == "admin"
    return getattr(user, "role", None) == "admin"


def _row_to_job(row: dict) -> JobRecord:
    return JobRecord(
        id=row["id"],
        name=row["name"],
        strategy=row["strategy"],
        job_type=row["job_type"],
        owner_id=row.get("owner_id"),
        config=json.loads(row["config"])
        if isinstance(row.get("config"), str)
        else (row.get("config") or {}),
        status=row["status"],
        is_active=row["is_active"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
    )


def _row_to_session(row: dict) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        job_id=row["job_id"],
        session_date=str(row["session_date"]),
        orb_high=float(row["orb_high"]) if row.get("orb_high") is not None else None,
        orb_low=float(row["orb_low"]) if row.get("orb_low") is not None else None,
        status=row["status"],
        total_entries=row.get("total_entries", 0),
        total_exits=row.get("total_exits", 0),
        daily_pnl_usd=round((row.get("daily_pnl_cents") or 0) / 100, 2),
        opened_at=row["opened_at"].isoformat() if row.get("opened_at") else "",
        closed_at=row["closed_at"].isoformat() if row.get("closed_at") else None,
    )


def _row_to_event(row: dict) -> EventRecord:
    return EventRecord(
        id=row["id"],
        time=row["time"].isoformat() if row.get("time") else "",
        event_type=row["event_type"],
        direction=row.get("direction"),
        contract_symbol=row.get("contract_symbol"),
        contracts=row.get("contracts"),
        spy_price=float(row["spy_price"]) if row.get("spy_price") is not None else None,
        orb_high=float(row["orb_high"]) if row.get("orb_high") is not None else None,
        orb_low=float(row["orb_low"]) if row.get("orb_low") is not None else None,
        signal_streak=row.get("signal_streak"),
        entry_counts=json.loads(row["entry_counts"])
        if isinstance(row.get("entry_counts"), str)
        else row.get("entry_counts"),
        option_price=float(row["option_price"]) if row.get("option_price") is not None else None,
        pnl_cents=row.get("pnl_cents"),
        order_id=row.get("order_id"),
        reason=row.get("reason"),
        decision=row.get("decision"),
    )


def _status() -> JobStatusResponse:
    return JobStatusResponse(**_build_status_response())


# ── Legacy single-job endpoints (backward compat → system job) ────────────────


@router.post("/start", response_model=JobStatusResponse)
async def start_job(request: Request, _user: Any = Depends(get_current_user)) -> JobStatusResponse:
    """Start the default system job. Idempotent."""
    await trading_job.start(pool=_get_pool(request))
    return _status()


@router.post("/stop", response_model=JobStatusResponse)
async def stop_job(_user: Any = Depends(get_current_user)) -> JobStatusResponse:
    """Stop the default system job gracefully."""
    await trading_job.stop()
    return _status()


@router.get("/status", response_model=JobStatusResponse)
async def get_status(_user: Any = Depends(get_current_user)) -> JobStatusResponse:
    """Current trading job state snapshot."""
    return _status()


@router.get("/log", response_model=list[TradeLogEntry])
async def get_log(_user: Any = Depends(get_current_user)) -> list[TradeLogEntry]:
    """Trade activity log (last 100 entries, in-memory)."""
    async with state_lock:
        entries = list(trading_state.trade_log[-100:])
    return [TradeLogEntry(**e) for e in entries]


@router.post("/reset", response_model=JobStatusResponse)
async def reset_job(_user: Any = Depends(get_current_user)) -> JobStatusResponse:
    """Stop the job and clear all state. Ready for a new session."""
    await trading_job.stop()
    reset_state()
    return _status()


# ── Job registry ──────────────────────────────────────────────────────────────


@router.post("/jobs", response_model=JobRecord, status_code=201)
async def create_job(
    body: CreateJobRequest,
    request: Request,
    user: Any = Depends(get_current_user),
) -> JobRecord:
    """Create a new trading job owned by the current user."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        # Check for duplicate name
        existing = await conn.fetchrow(
            "SELECT id FROM trading_jobs WHERE owner_id = $1 AND name = $2",
            user["id"],
            body.name,
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Job '{body.name}' already exists.")
        job_id = await trading_db.get_or_create_job(
            conn,
            name=body.name,
            strategy=body.strategy,
            job_type="user",
            owner_id=user["id"],
            config=body.config,
        )
        row = await trading_db.get_job(conn, job_id)
    if not row:
        raise HTTPException(status_code=500, detail="Job creation failed.")
    return _row_to_job(row)


@router.get("/jobs", response_model=list[JobRecord])
async def list_jobs(
    request: Request,
    user: Any = Depends(get_current_user),
) -> list[JobRecord]:
    """List all jobs visible to the current user (own jobs + system jobs)."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        rows = await trading_db.get_jobs(conn, user["id"], is_admin=_is_admin(user))
    return [_row_to_job(r) for r in rows]


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job(
    job_id: int,
    request: Request,
    user: Any = Depends(get_current_user),
) -> JobRecord:
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        ok = await trading_db.job_belongs_to_user(
            conn, job_id, user["id"], is_admin=_is_admin(user)
        )
        if not ok:
            raise HTTPException(status_code=403, detail="Access denied.")
        row = await trading_db.get_job(conn, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _row_to_job(row)


@router.post("/jobs/{job_id}/start", response_model=StartJobResponse)
async def start_specific_job(
    job_id: int,
    request: Request,
    user: Any = Depends(get_current_user),
) -> StartJobResponse:
    """Start a specific job. Enforces one-running-job-per-user isolation."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        # Permission: must own the job (or admin for system jobs)
        ok = await trading_db.can_mutate_job(conn, job_id, user["id"], is_admin=_is_admin(user))
        if not ok:
            raise HTTPException(status_code=403, detail="Access denied.")

        # Isolation: user may only run one job at a time
        if not _is_admin(user):
            has_running = await trading_db.user_has_running_job(conn, user["id"])
            if has_running:
                raise HTTPException(
                    status_code=409,
                    detail="You already have a running job. Stop it before starting another.",
                )

        await trading_db.set_job_status(conn, job_id, "running")
        today = datetime.now(tz=UTC).date()
        session_id = await trading_db.get_or_create_session(conn, job_id, today)
        job_row = await trading_db.get_job(conn, job_id)
        session_row = await conn.fetchrow(
            "SELECT * FROM trading_sessions WHERE id = $1", session_id
        )

    if not job_row or not session_row:
        raise HTTPException(status_code=500, detail="Failed to start job.")

    return StartJobResponse(
        job=_row_to_job(job_row),
        session=_row_to_session(dict(session_row)),
        message=f"Job '{job_row['name']}' started. Session {session_id} opened for {today}.",
    )


@router.post("/jobs/{job_id}/stop", response_model=JobRecord)
async def stop_specific_job(
    job_id: int,
    request: Request,
    user: Any = Depends(get_current_user),
) -> JobRecord:
    """Stop a specific job and close today's session."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        ok = await trading_db.can_mutate_job(conn, job_id, user["id"], is_admin=_is_admin(user))
        if not ok:
            raise HTTPException(status_code=403, detail="Access denied.")
        today = datetime.now(tz=UTC).date()
        session = await conn.fetchrow(
            "SELECT id, daily_pnl_cents FROM trading_sessions WHERE job_id = $1 AND session_date = $2",
            job_id,
            today,
        )
        if session:
            await trading_db.close_session(
                conn, session["id"], pnl_cents=session["daily_pnl_cents"] or 0
            )
        await trading_db.set_job_status(conn, job_id, "idle")
        row = await trading_db.get_job(conn, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _row_to_job(row)


@router.get("/jobs/{job_id}/sessions", response_model=list[SessionRecord])
async def list_sessions(
    job_id: int,
    request: Request,
    user: Any = Depends(get_current_user),
) -> list[SessionRecord]:
    """List all sessions for a job (most recent first)."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        ok = await trading_db.job_belongs_to_user(
            conn, job_id, user["id"], is_admin=_is_admin(user)
        )
        if not ok:
            raise HTTPException(status_code=403, detail="Access denied.")
        rows = await trading_db.get_sessions(conn, job_id)
    return [_row_to_session(r) for r in rows]


@router.get("/jobs/{job_id}/sessions/today")
async def get_today_session(
    job_id: int,
    request: Request,
    user: Any = Depends(get_current_user),
) -> dict:
    """Today's session + last 200 events for this job."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        ok = await trading_db.job_belongs_to_user(
            conn, job_id, user["id"], is_admin=_is_admin(user)
        )
        if not ok:
            raise HTTPException(status_code=403, detail="Access denied.")
        session_row = await trading_db.get_session_today(conn, job_id)
        if not session_row:
            return {"session": None, "events": []}
        events = await trading_db.get_events(conn, session_row["id"], limit=200)
    return {
        "session": _row_to_session(session_row),
        "events": [_row_to_event(e) for e in events],
    }


@router.get("/jobs/{job_id}/sessions/{session_id}/events", response_model=list[EventRecord])
async def get_session_events(
    job_id: int,
    session_id: int,
    request: Request,
    user: Any = Depends(get_current_user),
) -> list[EventRecord]:
    """Full event log for a specific session (max 500)."""
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        ok = await trading_db.job_belongs_to_user(
            conn, job_id, user["id"], is_admin=_is_admin(user)
        )
        if not ok:
            raise HTTPException(status_code=403, detail="Access denied.")
        events = await trading_db.get_events(conn, session_id, limit=500)
    return [_row_to_event(e) for e in events]
