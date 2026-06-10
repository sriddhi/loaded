"""Ingest tests for the fundamentals module (yfinance + DB mocked)."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.fundamentals.ingest import ingest_statements  # noqa: E402

_FAKE = {
    "equity": {"symbol": "NVDA", "name": "NVIDIA", "asset_class": "us_equity", "currency": "USD"},
    "annual": [
        {
            "period_type": "annual",
            "period_end": date(2024, 1, 31),
            "fiscal_year": 2024,
            "fiscal_quarter": None,
            "revenue": 1000_00,
            "net_income": 300_00,
        },
        {
            "period_type": "annual",
            "period_end": date(2023, 1, 31),
            "fiscal_year": 2023,
            "fiscal_quarter": None,
            "revenue": 800_00,
            "net_income": 200_00,
        },
    ],
    "quarterly": [
        {
            "period_type": "quarterly",
            "period_end": date(2024, 1, 31),
            "fiscal_year": 2024,
            "fiscal_quarter": 4,
            "revenue": 260_00,
            "net_income": 80_00,
        },
    ],
}


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    conn.execute = AsyncMock()
    return conn


@pytest.mark.asyncio
async def test_ingest_writes_all_periods():
    conn = _conn()
    with patch("app.fundamentals.ingest.fetch_raw_statements", AsyncMock(return_value=_FAKE)):
        result = await ingest_statements("NVDA", conn)
    assert result["symbol"] == "NVDA"
    assert result["periods_written"] == 3  # 2 annual + 1 quarterly
    assert conn.execute.await_count == 3  # one upsert per period
    assert conn.fetchrow.await_count == 1  # equity upsert


@pytest.mark.asyncio
async def test_ingest_idempotent_second_run():
    conn = _conn()
    with patch("app.fundamentals.ingest.fetch_raw_statements", AsyncMock(return_value=_FAKE)):
        await ingest_statements("NVDA", conn)
        await ingest_statements("NVDA", conn)
    # Same number of upserts each run (ON CONFLICT handles dedup at the DB layer).
    assert conn.execute.await_count == 6
