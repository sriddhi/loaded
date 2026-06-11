"""Tests for the SPY 0-3 DTE options paper job (pure logic; no network)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.options_paper_job import (  # noqa: E402
    _filled_price,
    spy_direction,
)


def _stock_client(closes: list[float]) -> MagicMock:
    bars = [SimpleNamespace(close=c) for c in closes]
    client = MagicMock()
    client.get_stock_bars.return_value = SimpleNamespace(data={"SPY": bars})
    return client


def test_direction_call_on_up_put_on_down_skip_flat():
    up = _stock_client([100, 100, 100, 100, 100, 100.5])  # +0.5% over 5
    assert spy_direction(up)[0] == "CALL"
    down = _stock_client([100, 100, 100, 100, 100, 99.5])  # -0.5%
    assert spy_direction(down)[0] == "PUT"
    flat = _stock_client([100, 100, 100, 100, 100, 100.0])
    assert spy_direction(flat)[0] == "SKIP"
    thin = _stock_client([100, 100])  # not enough bars
    assert spy_direction(thin)[0] == "SKIP"


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


def test_report_counts_right_wrong_and_total(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    import app.options_paper_job as job

    path = tmp_path / "report.json"
    monkeypatch.setattr(job, "REPORT_PATH", str(path))
    closed = [
        {"contract": "A", "pnl": 12.0, "right": True},
        {"contract": "B", "pnl": -6.0, "right": False},
        {"contract": "C", "pnl": 4.0, "right": True},
    ]
    job._write_report(closed, [], datetime.now(UTC))
    rep = json.loads(path.read_text())
    assert rep["decisions"] == 3
    assert rep["right"] == 2 and rep["wrong"] == 1
    assert rep["total_upside_usd"] == 10.0
    assert rep["win_rate_pct"] == 66.7
    assert rep["account"].startswith("ALPACA PAPER")
