# Tests for app/trading/state.py helpers.

from app.trading.state import log_error, log_event, reset_state, trading_state


def test_reset_clears_state():
    trading_state.status = "trading"
    trading_state.daily_pnl_cents = 99999
    reset_state()
    assert trading_state.status == "idle"
    assert trading_state.daily_pnl_cents == 0
    assert trading_state.open_positions == []


def test_log_event_appends():
    reset_state()
    log_event("entry", direction="CALL", price=3.50)
    assert len(trading_state.trade_log) == 1
    assert trading_state.trade_log[0]["action"] == "entry"


def test_log_event_caps_at_100():
    reset_state()
    for _i in range(110):
        log_event("entry")
    assert len(trading_state.trade_log) == 100


def test_log_error_caps_at_10():
    reset_state()
    for _i in range(15):
        log_error(f"error {_i}")
    assert len(trading_state.errors) == 10
    assert "error 14" in trading_state.errors[-1]
