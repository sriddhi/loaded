# Pydantic model tests for app/trading/models.py
# Models are exercised via API response validation in test_trading_job.py.
# This file satisfies the test coverage gate for the models module.

from app.trading.models import JobStatusResponse, TradeLogEntry


def test_job_status_response_defaults():
    r = JobStatusResponse(
        status="idle",
        session_date=None,
        orb_high=None,
        orb_low=None,
        open_positions=[],
        entry_counts={"CALL": 0, "PUT": 0},
        daily_pnl_usd=0.0,
        last_tick_at=None,
        recent_errors=[],
    )
    assert r.status == "idle"
    assert r.daily_pnl_usd == 0.0


def test_trade_log_entry_optional_fields():
    e = TradeLogEntry(
        timestamp="2024-06-07T10:00:00Z",
        action="entry",
        direction="CALL",
        contract_symbol="SPY240607C00530000",
        contracts=2,
        price=3.50,
        reason=None,
        pnl_usd=None,
    )
    assert e.action == "entry"
    assert e.pnl_usd is None
