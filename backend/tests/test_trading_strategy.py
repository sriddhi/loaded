"""Unit tests for app/trading/strategy.py — pure functions, no I/O."""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone

import pytest
from app.trading.state import OpenPosition, ORBLevels
from app.trading.strategy import (
    compute_orb,
    format_contract_symbol,
    select_strike,
    should_enter,
    should_exit,
    size_position,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_bars(n: int, high: float = 535.0, low: float = 530.0) -> list[dict]:
    return [
        {
            "time": f"2024-06-07T09:{30 + i:02d}:00Z",
            "open": 532.0,
            "high": high,
            "low": low,
            "close": 532.0,
        }
        for i in range(n)
    ]


def _make_orb(high: float = 535.0, low: float = 530.0) -> ORBLevels:
    return ORBLevels(
        high=high,
        low=low,
        width=round(high - low, 4),
        established_at=datetime.now(tz=UTC),
    )


def _make_position(direction: str = "CALL", entry_premium: float = 2.50) -> OpenPosition:
    return OpenPosition(
        contract_symbol="SPY240607C00530000",
        direction=direction,
        contracts=2,
        entry_premium=entry_premium,
        entry_order_id="test-order-id",
        opened_at=datetime.utcnow(),
    )


# ── compute_orb ───────────────────────────────────────────────────────────────


def test_compute_orb_normal():
    bars = _make_bars(30, high=536.0, low=531.0)
    orb = compute_orb(bars)
    assert orb is not None
    assert orb.high == 536.0
    assert orb.low == 531.0
    assert orb.width == pytest.approx(5.0)


def test_compute_orb_insufficient():
    bars = _make_bars(4)
    assert compute_orb(bars) is None


def test_compute_orb_empty():
    assert compute_orb([]) is None


def test_compute_orb_reject_thin():
    # ORB width < $0.10
    bars = _make_bars(10, high=530.05, low=530.00)
    assert compute_orb(bars) is None


def test_compute_orb_exact_boundary():
    # Exactly MIN_ORB_BARS bars
    bars = _make_bars(5, high=535.0, low=530.0)
    orb = compute_orb(bars)
    assert orb is not None


# ── should_enter ──────────────────────────────────────────────────────────────


def test_should_enter_call_breakout():
    orb = _make_orb(high=535.0, low=530.0)
    result = should_enter(
        "CALL",
        spy_price=535.50,
        orb=orb,
        open_positions=[],
        entry_counts={"CALL": 0, "PUT": 0},
        signal_streak={"CALL": 2, "PUT": 0},
    )
    assert result is True


def test_should_enter_no_signal_inside_orb():
    orb = _make_orb(high=535.0, low=530.0)
    # Price inside ORB
    result = should_enter(
        "CALL",
        spy_price=532.0,
        orb=orb,
        open_positions=[],
        entry_counts={"CALL": 0, "PUT": 0},
        signal_streak={"CALL": 2, "PUT": 0},
    )
    assert result is False


def test_should_enter_max_entries_reached():
    orb = _make_orb(high=535.0, low=530.0)
    result = should_enter(
        "CALL",
        spy_price=536.0,
        orb=orb,
        open_positions=[],
        entry_counts={"CALL": 3, "PUT": 0},
        signal_streak={"CALL": 2, "PUT": 0},
    )
    assert result is False


def test_should_enter_already_open_same_direction():
    orb = _make_orb(high=535.0, low=530.0)
    open_pos = [_make_position("CALL")]
    result = should_enter(
        "CALL",
        spy_price=536.0,
        orb=orb,
        open_positions=open_pos,
        entry_counts={"CALL": 1, "PUT": 0},
        signal_streak={"CALL": 2, "PUT": 0},
    )
    assert result is False


def test_should_enter_open_call_allows_put():
    orb = _make_orb(high=535.0, low=530.0)
    open_pos = [_make_position("CALL")]
    result = should_enter(
        "PUT",
        spy_price=529.0,
        orb=orb,
        open_positions=open_pos,
        entry_counts={"CALL": 1, "PUT": 0},
        signal_streak={"CALL": 0, "PUT": 2},
    )
    assert result is True


def test_should_enter_streak_too_low():
    orb = _make_orb(high=535.0, low=530.0)
    result = should_enter(
        "CALL",
        spy_price=536.0,
        orb=orb,
        open_positions=[],
        entry_counts={"CALL": 0, "PUT": 0},
        signal_streak={"CALL": 1, "PUT": 0},  # needs 2
    )
    assert result is False


# ── should_exit ───────────────────────────────────────────────────────────────


def _et_time(hour: int, minute: int = 0) -> datetime:
    from datetime import timedelta

    et = timezone(timedelta(hours=-4))
    return datetime.now(tz=et).replace(hour=hour, minute=minute, second=0, microsecond=0)


def test_should_exit_take_profit():
    pos = _make_position(entry_premium=2.00)
    flag, reason = should_exit(pos, current_mark=3.62, current_time=_et_time(11))
    assert flag is True
    assert reason == "take_profit"


def test_should_exit_stop_loss():
    pos = _make_position(entry_premium=2.00)
    flag, reason = should_exit(pos, current_mark=0.88, current_time=_et_time(11))
    assert flag is True
    assert reason == "stop_loss"


def test_should_exit_time_stop():
    pos = _make_position(entry_premium=2.00)
    flag, reason = should_exit(pos, current_mark=2.00, current_time=_et_time(15, 46))
    assert flag is True
    assert reason == "time_stop"


def test_should_exit_hold():
    pos = _make_position(entry_premium=2.00)
    # mark is between stop and take-profit, before time stop
    flag, reason = should_exit(pos, current_mark=2.50, current_time=_et_time(11))
    assert flag is False
    assert reason == "hold"


# ── Position sizing ───────────────────────────────────────────────────────────


def test_size_position_normal():
    # $100k portfolio, $3.00 ask → risk=$3k, cost/contract=$300 → 10 (capped)
    result = size_position(portfolio_value=100_000, ask_price=3.00)
    assert result == 10


def test_size_position_small_account():
    # $10k portfolio, $5.00 ask → risk=$300, cost=$500 → floor(0.6)=0 → min 1
    result = size_position(portfolio_value=10_000, ask_price=5.00)
    assert result >= 1


def test_size_position_min_1():
    # Very expensive option
    result = size_position(portfolio_value=5_000, ask_price=50.00)
    assert result == 1


# ── Contract symbol ───────────────────────────────────────────────────────────


def test_format_contract_symbol_call():
    sym = format_contract_symbol(date(2024, 6, 7), "CALL", 530)
    assert sym == "SPY240607C00530000"


def test_format_contract_symbol_put():
    sym = format_contract_symbol(date(2024, 6, 7), "PUT", 529)
    assert sym == "SPY240607P00529000"


def test_select_strike_rounds():
    assert select_strike(530.7, "CALL") == 531
    assert select_strike(530.4, "PUT") == 530
