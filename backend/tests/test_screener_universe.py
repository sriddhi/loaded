"""Universe seed integrity + refresh behavior."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.screener.universe import UNIVERSE_SEED, refresh_universe  # noqa: E402


def test_seed_size_and_universes():
    universes = {u for *_, u in UNIVERSE_SEED}
    assert universes == {"sp500", "ndx100"}
    sp = [s for s, *_, u in [(r[0], r[3]) for r in UNIVERSE_SEED] if u == "sp500"]
    assert 480 <= len(sp) <= 520
    unique = {r[0] for r in UNIVERSE_SEED}
    assert 500 <= len(unique) <= 570


def test_seed_no_duplicate_symbol_universe_pairs():
    pairs = [(r[0], r[3]) for r in UNIVERSE_SEED]
    assert len(pairs) == len(set(pairs))


def test_overlap_symbols_in_both():
    sp = {r[0] for r in UNIVERSE_SEED if r[3] == "sp500"}
    ndx = {r[0] for r in UNIVERSE_SEED if r[3] == "ndx100"}
    overlap = sp & ndx
    assert "AAPL" in overlap and "MSFT" in overlap  # megacaps live in both
    assert len(overlap) >= 60


def test_seed_shapes():
    for sym, name, sector, _uni in UNIVERSE_SEED:
        assert sym and sym == sym.upper() and "." not in sym  # class shares use dash
        assert name and sector


@pytest.mark.asyncio
async def test_refresh_upserts_without_clobbering():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    out = await refresh_universe(pool)
    assert out["total"] >= 500
    equity_sql = conn.fetchrow.await_args_list[0].args[0]
    assert "COALESCE(equities.gics_sector, EXCLUDED.gics_sector)" in equity_sql
    # departed members flagged, never deleted
    stale_sql = conn.execute.await_args_list[-1].args[0]
    assert "is_current = FALSE" in stale_sql and "DELETE" not in stale_sql
