"""Data pipeline: chunking, staleness selection, idempotent upserts."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.screener.data import _chunks, stale_statement_symbols  # noqa: E402


def test_chunking_math():
    symbols = [f"S{i}" for i in range(550)]
    chunks = _chunks(symbols, 50)
    assert len(chunks) == 11
    assert sum(len(c) for c in chunks) == 550
    assert _chunks([], 50) == []


@pytest.mark.asyncio
async def test_stale_selection_and_order():
    now = datetime.now(UTC)
    pool = MagicMock()
    pool.fetch = AsyncMock(
        return_value=[
            {"symbol": "FRESH", "newest": now - timedelta(days=2)},
            {"symbol": "OLD", "newest": now - timedelta(days=45)},
            {"symbol": "NEVER", "newest": None},
            {"symbol": "OLDER", "newest": now - timedelta(days=90)},
        ]
    )
    stale = await stale_statement_symbols(pool, ["FRESH", "OLD", "NEVER", "OLDER"])
    assert stale == ["NEVER", "OLDER", "OLD"]  # stalest first, fresh excluded


@pytest.mark.asyncio
async def test_refresh_closes_upsert_is_idempotent_and_skips_bad_chunks():
    from unittest.mock import patch

    from app.screener.data import refresh_closes

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.executemany = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    pool.fetch = AsyncMock(
        side_effect=[
            [{"id": i, "symbol": s} for i, s in enumerate(["AAA", "SPY", "IGV", "SMH"])],
            [],  # no existing 1d bars → first run
        ]
    )
    bars = {
        "AAA": [
            {
                "ts": datetime(2026, 6, 11, tzinfo=UTC),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
            }
        ]
    }
    calls = {"n": 0}

    def fake_download(chunk, lookback):  # first chunk ok, others raise
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("rate limited")
        return bars

    with patch("app.screener.data._download_chunk", side_effect=fake_download):
        written = await refresh_closes(pool, ["AAA"], chunk_size=2)
    assert written == {"AAA": 1}
    sql = conn.executemany.await_args.args[0]
    assert "ON CONFLICT (equity_id, timeframe, time) DO UPDATE" in sql
