"""Pydantic models for the trading API."""

from __future__ import annotations

from pydantic import BaseModel


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
