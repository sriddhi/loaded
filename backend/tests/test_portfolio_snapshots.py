"""Snapshot valuation fallback chain, flows, gating, idempotency."""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.portfolio.snapshots import (  # noqa: E402
    PortfolioSnapshotScheduler,
    snapshot_all,
    snapshot_portfolio,
)

ET = ZoneInfo("America/New_York")


def _pool(holdings: list[dict], bar_rows: list[dict], last_detail: dict | None = None):
    pool = MagicMock()
    pool.fetch = AsyncMock(side_effect=[holdings, bar_rows])
    pool.fetchrow = AsyncMock(
        return_value={"detail": last_detail} if last_detail is not None else None
    )
    pool.fetchval = AsyncMock(return_value=-5_000)  # net flow (withdrawal day)
    pool.execute = AsyncMock()
    return pool


def _holding(sym: str, qty: str, avg: int) -> dict:
    return {
        "symbol": sym,
        "qty": Decimal(qty),
        "avg_cost_cents": avg,
        "cost_basis_cents": int(Decimal(qty) * avg),
        "realized_pnl_cents": 0,
    }


@pytest.mark.asyncio
async def test_fallback_chain_bar_then_carry_then_cost():
    holdings = [_holding("A", "1", 10_000), _holding("B", "1", 20_000), _holding("C", "1", 30_000)]
    bars = [{"symbol": "A", "close": 110.0}]  # only A has today's bar
    carry = {"B": {"price": 222.0}}  # B carried from last snapshot
    pool = _pool(holdings, bars, last_detail=carry)
    with patch("app.fundamentals.price_fallback.resolve_price", AsyncMock(return_value=None)):
        await snapshot_portfolio(pool, {"id": 7, "cash_cents": 50_000})
    args = pool.execute.await_args.args
    sql, detail_json = args[0], args[10]
    assert "ON CONFLICT (portfolio_id, snapshot_date) DO UPDATE" in sql  # idempotent
    import json

    detail = json.loads(detail_json)
    assert detail["A"]["src"] == "bar" and detail["A"]["price"] == 110.0
    assert detail["B"]["src"] == "carried" and detail["B"]["price"] == 222.0
    assert detail["C"]["src"] == "cost" and detail["C"]["price"] == 300.0
    # equity = 110 + 222 + 300 = 632.00 → 63_200 cents; total = +cash 50_000
    assert args[3] == 63_200 and args[5] == 113_200
    assert args[6] == -5_000  # net flow passthrough


def test_due_gating():
    sched = PortfolioSnapshotScheduler(MagicMock())
    assert sched._due(datetime(2026, 6, 12, 16, 15, tzinfo=ET)) is True
    assert sched._due(datetime(2026, 6, 12, 16, 0, tzinfo=ET)) is False
    assert sched._due(datetime(2026, 6, 14, 17, 0, tzinfo=ET)) is False  # Sunday


@pytest.mark.asyncio
async def test_snapshot_all_isolates_failures():
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[{"id": 1, "cash_cents": 0}, {"id": 2, "cash_cents": 0}])
    with patch(
        "app.portfolio.snapshots.snapshot_portfolio",
        AsyncMock(side_effect=[RuntimeError("boom"), {"portfolio_id": 2}]),
    ):
        done = await snapshot_all(pool)
    assert done == 1  # second portfolio still snapshotted
