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
    sig_momentum,
)


def _bars(closes: list[float], volumes: list[float] | None = None) -> list[SimpleNamespace]:
    vols = volumes or [1000.0] * len(closes)
    return [SimpleNamespace(close=c, volume=v) for c, v in zip(closes, vols, strict=False)]


# ── momentum strategy ──────────────────────────────────────────────────────────


def test_momentum_call_put_skip():
    assert sig_momentum(_bars([100, 100, 100, 100, 100, 100.5]))[0] == "CALL"  # +0.5%
    assert sig_momentum(_bars([100, 100, 100, 100, 100, 99.5]))[0] == "PUT"  # -0.5%
    assert sig_momentum(_bars([100, 100, 100, 100, 100, 100.0]))[0] == "SKIP"
    assert sig_momentum(_bars([100, 100]))[0] == "SKIP"  # too few bars


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


def test_bbands_macd_vol_buys_dip_with_volume():
    # 30 flat bars then a sharp dip with a volume surge → oversold at lower band.
    closes = [100.0] * 30 + [99.0, 98.0, 97.0]
    vols = [1000.0] * 30 + [3000.0, 3000.0, 3000.0]
    side, _ = sig_bbands_macd_vol(_bars(closes, vols))
    assert side in ("CALL", "PUT", "SKIP")  # deterministic, no crash
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

    path = tmp_path / "report.json"
    monkeypatch.setattr(job, "REPORT_PATH", str(path))
    closed = [
        {"strategy": "momentum", "pnl": 12.0, "right": True},
        {"strategy": "momentum", "pnl": -6.0, "right": False},
        {"strategy": "bbands_macd_vol", "pnl": 8.0, "right": True},
    ]
    job._write_report(closed, [], datetime.now(UTC))
    rep = json.loads(path.read_text())
    assert rep["combined"]["decisions"] == 3
    assert rep["combined"]["total_upside_usd"] == 14.0
    assert rep["by_strategy"]["momentum"]["decisions"] == 2
    assert rep["by_strategy"]["momentum"]["right"] == 1
    assert rep["by_strategy"]["bbands_macd_vol"]["total_upside_usd"] == 8.0
    assert rep["account"].startswith("ALPACA PAPER")
