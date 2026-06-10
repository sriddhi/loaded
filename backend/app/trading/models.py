"""Pydantic models for the trading API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# ── In-memory status (legacy / fast read) ────────────────────────────────────


class PositionSummary(BaseModel):
    contract_symbol: str
    direction: str
    contracts: int
    entry_premium: float
    current_mark: float | None
    unrealized_pnl_usd: float | None


class JobStatusResponse(BaseModel):
    status: str
    session_date: str | None
    orb_high: float | None
    orb_low: float | None
    open_positions: list[PositionSummary]
    entry_counts: dict[str, int]
    daily_pnl_usd: float
    last_tick_at: str | None
    recent_errors: list[str]


class TradeLogEntry(BaseModel):
    timestamp: str
    action: str
    direction: str | None
    contract_symbol: str | None
    contracts: int | None
    price: float | None
    reason: str | None
    pnl_usd: float | None


# ── DB-backed multi-job models ────────────────────────────────────────────────


class JobRecord(BaseModel):
    id: int
    name: str
    strategy: str
    job_type: str  # 'system' | 'user'
    owner_id: int | None
    config: dict[str, Any]
    status: str
    is_active: bool
    created_at: str


class SessionRecord(BaseModel):
    id: int
    job_id: int
    session_date: str
    orb_high: float | None
    orb_low: float | None
    status: str
    total_entries: int
    total_exits: int
    daily_pnl_usd: float
    opened_at: str
    closed_at: str | None


class EventRecord(BaseModel):
    id: int
    time: str
    event_type: str
    direction: str | None
    contract_symbol: str | None
    contracts: int | None
    spy_price: float | None
    orb_high: float | None
    orb_low: float | None
    signal_streak: int | None
    entry_counts: dict[str, Any] | None
    option_price: float | None
    pnl_cents: int | None
    order_id: str | None
    reason: str | None
    decision: str | None


class CreateJobRequest(BaseModel):
    name: str
    strategy: str = "orb"
    config: dict[str, Any] = {}  # noqa: RUF012


class StartJobResponse(BaseModel):
    job: JobRecord
    session: SessionRecord
    message: str
