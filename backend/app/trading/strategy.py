"""
Pure strategy functions — no I/O, no side effects.

All functions take plain data and return decisions.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any

from app.trading.state import OpenPosition, ORBLevels

# ── Constants ─────────────────────────────────────────────────────────────────

TAKE_PROFIT_MULT = 1.80  # exit at 80% gain
STOP_LOSS_MULT = 0.45  # exit at 55% loss
TIME_STOP_HOUR = 15
TIME_STOP_MINUTE = 45
MAX_ENTRIES_PER_DIRECTION = 3
SIGNAL_STREAK_REQUIRED = 2
RISK_PER_TRADE_PCT = 0.03
MAX_CONTRACTS = 10
MIN_ORB_WIDTH = 0.10
MIN_ORB_BARS = 5


# ── ORB ───────────────────────────────────────────────────────────────────────


def compute_orb(bars: list[dict[str, Any]]) -> ORBLevels | None:
    """Given 1-min bars for 9:30–10:00 ET, return ORB levels.

    Args:
        bars: list of dicts with keys: time (ISO str), open, high, low, close

    Returns:
        ORBLevels or None if insufficient/invalid data
    """
    if not bars or len(bars) < MIN_ORB_BARS:
        return None

    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]

    orb_high = max(highs)
    orb_low = min(lows)
    width = round(orb_high - orb_low, 4)

    if width < MIN_ORB_WIDTH:
        return None

    return ORBLevels(
        high=round(orb_high, 4),
        low=round(orb_low, 4),
        width=width,
        established_at=datetime.now(tz=UTC),
    )


# ── Entry ─────────────────────────────────────────────────────────────────────


def should_enter(
    direction: str,
    spy_price: float,
    orb: ORBLevels,
    open_positions: list[OpenPosition],
    entry_counts: dict[str, int],
    signal_streak: dict[str, int],
) -> bool:
    """Return True if entry conditions are fully met.

    Conditions (all must be true):
    - Price breakout beyond ORB level for the given direction
    - No open position in this direction already (no pyramiding)
    - entry_count < MAX_ENTRIES_PER_DIRECTION
    - signal_streak >= SIGNAL_STREAK_REQUIRED (2 consecutive checks)
    """
    # Count existing open positions for this direction
    already_open = any(p.direction == direction for p in open_positions)
    if already_open:
        return False

    if entry_counts.get(direction, 0) >= MAX_ENTRIES_PER_DIRECTION:
        return False

    if signal_streak.get(direction, 0) < SIGNAL_STREAK_REQUIRED:
        return False

    if direction == "CALL":
        return bool(spy_price > orb.high)
    if direction == "PUT":
        return bool(spy_price < orb.low)

    return False


# ── Exit ──────────────────────────────────────────────────────────────────────


def should_exit(
    position: OpenPosition,
    current_mark: float,
    current_time: datetime,
) -> tuple[bool, str]:
    """Return (should_exit, reason).

    reason: 'take_profit' | 'stop_loss' | 'time_stop' | 'hold'
    """
    # Time stop — always respect regardless of P&L
    et_hour = current_time.hour
    et_minute = current_time.minute
    if et_hour > TIME_STOP_HOUR or (et_hour == TIME_STOP_HOUR and et_minute >= TIME_STOP_MINUTE):
        return True, "time_stop"

    entry = position.entry_premium
    if entry <= 0:
        return False, "hold"

    if current_mark >= entry * TAKE_PROFIT_MULT:
        return True, "take_profit"

    if current_mark <= entry * STOP_LOSS_MULT:
        return True, "stop_loss"

    return False, "hold"


# ── Contract selection ────────────────────────────────────────────────────────


def select_strike(spy_price: float, direction: str) -> int:  # noqa: ARG001
    """Return ATM strike as integer dollar amount.

    ATM = round to nearest dollar. No moneyness bias in v1.
    """
    return int(round(spy_price))


def format_contract_symbol(expiry: date, direction: str, strike: int) -> str:
    """Return OCC symbol: SPY{YYMMDD}{C|P}{strike×1000 zero-padded to 8 digits}.

    Example: SPY call, 2024-06-07, strike $530 → SPY240607C00530000
    """
    yy = expiry.strftime("%y")
    mm = expiry.strftime("%m")
    dd = expiry.strftime("%d")
    cp = "C" if direction == "CALL" else "P"
    strike_str = str(strike * 1000).zfill(8)
    return f"SPY{yy}{mm}{dd}{cp}{strike_str}"


# ── Position sizing ───────────────────────────────────────────────────────────


def size_position(portfolio_value: float, ask_price: float) -> int:
    """Return number of contracts (1–MAX_CONTRACTS).

    risk_per_trade = portfolio_value × RISK_PER_TRADE_PCT
    cost_per_contract = ask_price × 100
    contracts = floor(risk_per_trade / cost_per_contract)
    clamped to [1, MAX_CONTRACTS]
    """
    if ask_price <= 0 or portfolio_value <= 0:
        return 1

    risk = portfolio_value * RISK_PER_TRADE_PCT
    cost_per = ask_price * 100.0

    contracts = math.floor(risk / cost_per)
    return max(1, min(contracts, MAX_CONTRACTS))
