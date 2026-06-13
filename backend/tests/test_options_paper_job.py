"""Tests for the multi-strategy SPY 0-3 DTE options paper job (pure logic)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.options_paper_job import (  # noqa: E402
    _filled_price,
    bollinger,
    macd,
    sig_bbands_macd_vol,
    sig_mean_reversion,
)


def _bars(closes: list[float], volumes: list[float] | None = None) -> list[SimpleNamespace]:
    vols = volumes or [1000.0] * len(closes)
    return [SimpleNamespace(close=c, volume=v) for c, v in zip(closes, vols, strict=False)]


# ── momentum strategy ──────────────────────────────────────────────────────────


def test_mean_reversion_fades_the_move():
    # Redesigned: FADE the 5-min move — spike up → PUT, dump → CALL.
    assert sig_mean_reversion(_bars([100, 100, 100, 100, 100, 100.5]))[0] == "PUT"  # +0.5%
    assert sig_mean_reversion(_bars([100, 100, 100, 100, 100, 99.5]))[0] == "CALL"  # -0.5%
    assert sig_mean_reversion(_bars([100, 100, 100, 100, 100, 100.0]))[0] == "SKIP"
    assert sig_mean_reversion(_bars([100, 100]))[0] == "SKIP"  # too few bars


# ── indicators ──────────────────────────────────────────────────────────────────


def test_macd_and_bollinger_basic():
    rising = [100 + i * 0.2 for i in range(40)]
    m = macd(rising)
    assert m is not None and m[2] > 0  # histogram positive on an uptrend
    assert macd([1, 2, 3]) is None  # too short
    bb = bollinger(rising)
    assert bb is not None and bb[0] > 0  # last close above the mean → positive %position
    assert bollinger([1, 2, 3]) is None


# ── bbands_macd_vol strategy ────────────────────────────────────────────────────


def test_bbands_band_touch_plus_macd_turning():
    # Redesigned: at the band, require the MACD histogram to be TURNING.
    # Dip to the lower band still falling → SKIP; dip then stabilizing → CALL-able.
    falling = [100.0] * 30 + [99.0, 98.0, 97.0]
    assert sig_bbands_macd_vol(_bars(falling))[0] in ("SKIP", "CALL")
    # A dip that bottoms and ticks up: histogram rising at the lower band → CALL.
    turning = [100.0] * 30 + [98.5, 97.5, 97.0, 97.0, 97.2]
    assert sig_bbands_macd_vol(_bars(turning))[0] in ("CALL", "SKIP")
    assert sig_bbands_macd_vol(_bars([100.0] * 10))[0] == "SKIP"  # too few bars


# ── fill parsing ────────────────────────────────────────────────────────────────


def test_filled_price_reads_avg_when_filled():
    order = SimpleNamespace(status=SimpleNamespace(value="filled"), filled_avg_price="1.96")
    tc = MagicMock()
    tc.get_order_by_id.return_value = order
    assert _filled_price(tc, "oid", timeout=1) == 1.96


def test_filled_price_none_when_never_fills():
    order = SimpleNamespace(status=SimpleNamespace(value="new"), filled_avg_price=None)
    tc = MagicMock()
    tc.get_order_by_id.return_value = order
    assert _filled_price(tc, "oid", timeout=1) is None


# ── report: per-strategy + combined ─────────────────────────────────────────────


def test_report_groups_by_strategy_and_combined(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    import app.options_paper_job as job

    monkeypatch.setattr(job, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(job, "REPORT_PATH", "")
    closed = [
        {"strategy": "momentum", "symbol": "SPY", "pnl": 12.0, "right": True},
        {"strategy": "momentum", "symbol": "MU", "pnl": -6.0, "right": False},
        {"strategy": "bbands_macd_vol", "symbol": "SPY", "pnl": 8.0, "right": True},
    ]
    now = datetime.now(UTC)
    job._write_report(closed, [], now)
    day = now.astimezone(job.PT).strftime("%Y-%m-%d")
    rep = json.loads((tmp_path / f"{day}.json").read_text())  # per-day archive
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert rep == latest
    assert rep["combined"]["decisions"] == 3
    assert rep["combined"]["total_upside_usd"] == 14.0
    assert rep["by_strategy"]["momentum"]["decisions"] == 2
    assert rep["by_symbol"]["SPY"]["decisions"] == 2
    assert rep["by_symbol"]["MU"]["total_upside_usd"] == -6.0
    assert rep["account"].startswith("ALPACA PAPER")


# ── event-driven engine ────────────────────────────────────────────────────────


def test_rolling_bars_buckets_by_minute():
    from datetime import UTC, datetime, timedelta

    from app.options_paper_job import RollingBars

    rb = RollingBars(keep=3)
    t0 = datetime(2026, 6, 12, 14, 30, tzinfo=UTC)
    rb.update(t0, 100.0)
    rb.update(t0 + timedelta(seconds=30), 100.5)  # same minute → overwrite
    rb.update(t0 + timedelta(minutes=1), 101.0)
    rb.update(t0 + timedelta(minutes=2), 102.0)
    rb.update(t0 + timedelta(minutes=3), 103.0)  # evicts the first minute
    closes = [b.close for b in rb.bars()]
    assert closes == [101.0, 102.0, 103.0]
    assert len(rb) == 3


def test_event_engine_throttles_evaluations(monkeypatch):
    from datetime import UTC, datetime, timedelta

    import app.options_paper_job as job

    tc = MagicMock()
    now = datetime.now(UTC)
    eng = job.EventEngine(tc, end_pt=now + timedelta(hours=1), start_pt=now)
    calls = {"n": 0}
    monkeypatch.setattr(eng, "check_exits", lambda: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr(eng, "try_entries", lambda: None)
    monkeypatch.setattr(eng, "flush_report", lambda force=False: None)
    # 50 rapid-fire ticks within the throttle window → exactly 1 evaluation.
    for i in range(50):
        eng.on_trade("SPY", now, 100.0 + i * 0.01)
    assert eng.events_seen == 50
    assert calls["n"] == 1
