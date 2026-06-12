"""Tests for the 0-2 DTE option research harness (pure functions only)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.options_research import (  # noqa: E402
    bs_price,
    realized_vol_annualized,
    run_day,
    summarize,
)


def test_bs_price_basics():
    # ATM call with vol/time has positive premium > intrinsic.
    px = bs_price(100.0, 100.0, t_years=10 / 365, sigma=0.4, call=True)
    assert px > 0
    # At expiry → intrinsic.
    assert bs_price(105.0, 100.0, 0.0, 0.4, call=True) == 5.0
    assert bs_price(95.0, 100.0, 0.0, 0.4, call=True) == 0.0
    assert bs_price(95.0, 100.0, 0.0, 0.4, call=False) == 5.0
    # Put-call parity (r=0): C − P = S − K.
    c = bs_price(102.0, 100.0, 5 / 365, 0.5, call=True)
    p = bs_price(102.0, 100.0, 5 / 365, 0.5, call=False)
    assert abs((c - p) - 2.0) < 1e-9


def test_realized_vol_bounds():
    flat = [100.0] * 100
    assert realized_vol_annualized(flat) >= 0.15  # floored
    wild = [100.0 * (1.05 if i % 2 else 0.95) ** 1 for i in range(100)]
    assert realized_vol_annualized(wild) <= 2.0  # capped


def _bars(closes: list[float]) -> list[SimpleNamespace]:
    t0 = datetime(2026, 6, 12, 13, 30, tzinfo=UTC)  # 09:30 ET
    return [
        SimpleNamespace(close=c, timestamp=t0 + timedelta(minutes=i)) for i, c in enumerate(closes)
    ]


def test_run_day_fades_a_spike_and_records_exits():
    # Flat, sharp spike up (entry: fade → PUT), then a fall (put gains → TP).
    closes = [100.0] * 50 + [101.5] + [99.0] * 30
    trades = run_day(_bars(closes), threshold=0.005, tp=0.5, sl=0.5, time_stop_min=20, dte=0)
    assert len(trades) >= 1
    t = trades[0]
    assert t["side"] == "PUT"  # faded the up-spike
    assert t["exit_reason"] in ("tp", "sl", "time", "eod")
    s = summarize(trades)
    assert s["n"] == len(trades) and 0 <= s["hit_rate"] <= 100


def test_run_day_too_short_returns_empty():
    assert (
        run_day(_bars([100.0] * 10), threshold=0.005, tp=0.5, sl=0.5, time_stop_min=20, dte=0) == []
    )


def test_summarize_empty():
    assert summarize([]) == {"n": 0}
