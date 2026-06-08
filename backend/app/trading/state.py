"""
In-memory trading session state.

Single module-level instance `trading_state` protected by `state_lock`.
Resets on job restart via `reset_state()`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class ORBLevels:
    high: float
    low: float
    width: float
    established_at: datetime


@dataclass
class OpenPosition:
    contract_symbol: str
    direction: str  # "CALL" | "PUT"
    contracts: int
    entry_premium: float  # per-share price paid (e.g. $2.50)
    entry_order_id: str
    opened_at: datetime


@dataclass
class TradingState:
    status: str  # "idle" | "capturing_orb" | "trading" | "closed" | "stopped"
    orb: ORBLevels | None
    open_positions: list[OpenPosition]
    entry_counts: dict[str, int]  # {"CALL": 0, "PUT": 0}
    daily_pnl_cents: int  # running P&L in cents for the session
    session_date: date | None
    last_tick_at: datetime | None
    signal_streak: dict[str, int]  # {"CALL": 0, "PUT": 0}
    errors: list[str]  # last 10 errors
    trade_log: list[dict]  # last 100 trade events


def _fresh_state() -> TradingState:
    return TradingState(
        status="idle",
        orb=None,
        open_positions=[],
        entry_counts={"CALL": 0, "PUT": 0},
        daily_pnl_cents=0,
        session_date=None,
        last_tick_at=None,
        signal_streak={"CALL": 0, "PUT": 0},
        errors=[],
        trade_log=[],
    )


trading_state: TradingState = _fresh_state()
state_lock: asyncio.Lock = asyncio.Lock()


def reset_state() -> None:
    """Reset trading_state fields in-place (preserves object identity for importers)."""
    fresh = _fresh_state()
    trading_state.status = fresh.status
    trading_state.orb = fresh.orb
    trading_state.open_positions = fresh.open_positions
    trading_state.entry_counts = fresh.entry_counts
    trading_state.daily_pnl_cents = fresh.daily_pnl_cents
    trading_state.session_date = fresh.session_date
    trading_state.last_tick_at = fresh.last_tick_at
    trading_state.signal_streak = fresh.signal_streak
    trading_state.errors = fresh.errors
    trading_state.trade_log = fresh.trade_log


def log_event(
    action: str,
    *,
    direction: str | None = None,
    contract_symbol: str | None = None,
    contracts: int | None = None,
    price: float | None = None,
    reason: str | None = None,
    pnl_usd: float | None = None,
) -> None:
    """Append a trade event. Caps log at 100 entries."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": action,
        "direction": direction,
        "contract_symbol": contract_symbol,
        "contracts": contracts,
        "price": price,
        "reason": reason,
        "pnl_usd": pnl_usd,
    }
    trading_state.trade_log.append(entry)
    if len(trading_state.trade_log) > 100:
        trading_state.trade_log = trading_state.trade_log[-100:]


def log_error(msg: str) -> None:
    """Append error. Caps at 10 entries."""
    trading_state.errors.append(msg)
    if len(trading_state.errors) > 10:
        trading_state.errors = trading_state.errors[-10:]
