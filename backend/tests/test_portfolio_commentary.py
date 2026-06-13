"""Commentary: cache, force, provider dispatch, disclaimer, context cap."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.portfolio.commentary import (  # noqa: E402
    CONTEXT_CAP_BYTES,
    DISCLAIMER_LINE,
    CommentaryUnavailableError,
    build_context,
    generate,
)


def _pool(cached_row=None):
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    pool.fetchrow = AsyncMock(return_value=cached_row)
    return pool, conn


def _ctx() -> dict:
    return {"portfolio": {"name": "X"}, "top_holdings": []}


@pytest.mark.asyncio
async def test_same_day_cache_hit_skips_provider():
    cached = {
        "analysis": {"markdown": "cached text"},
        "version": 3,
        "data_as_of": datetime.now(UTC),
    }
    pool, conn = _pool(cached_row=cached)
    with patch("app.portfolio.commentary._generate_markdown", AsyncMock()) as gen:
        out = await generate(pool, 1, 7, _ctx())
    assert out["cached"] is True and out["markdown"] == "cached text" and out["version"] == 3
    gen.assert_not_awaited()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_regenerates_and_bumps_version():
    cached = {
        "analysis": {"markdown": "old"},
        "version": 3,
        "data_as_of": datetime.now(UTC),
    }
    pool, conn = _pool(cached_row=cached)
    conn.fetchval = AsyncMock(return_value=4)  # next version
    with patch(
        "app.portfolio.commentary._generate_markdown",
        AsyncMock(return_value=f"fresh\n\n{DISCLAIMER_LINE}"),
    ):
        out = await generate(pool, 1, 7, _ctx(), force=True)
    assert out["cached"] is False and out["version"] == 4
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_disclaimer_appended_when_model_omits():
    from app.portfolio.commentary import _generate_markdown

    with (
        patch.dict(os.environ, {"STRATEGY_CHAT_PROVIDER": "claude_code"}),
        patch("app.strategies.chat._bridge_chat", AsyncMock(return_value="no disclaimer here")),
    ):
        text = await _generate_markdown(_ctx())
    assert text.endswith(DISCLAIMER_LINE)


@pytest.mark.asyncio
async def test_provider_failure_raises_and_never_caches():
    pool, conn = _pool()
    with (
        patch.dict(os.environ, {"STRATEGY_CHAT_PROVIDER": "claude_code"}),
        patch("app.strategies.chat._bridge_chat", AsyncMock(side_effect=RuntimeError("down"))),
        pytest.raises(CommentaryUnavailableError),
    ):
        await generate(pool, 1, 7, _ctx())
    conn.execute.assert_not_awaited()


def test_context_cap_trims_holdings():
    holdings = [
        {
            "symbol": f"S{'X' * 400}{i}",  # absurdly long symbols inflate the JSON
            "weight_pct": 1.0,
            "unrealized_pct": 1.0,
            "market_value": 1.0,
        }
        for i in range(12)
    ]
    insights = {"holdings_signals": {"items": []}, "health": {"checks": []}, "macro_impacts": []}
    ctx = build_context({"name": "big"}, holdings, insights, None)
    assert len(json.dumps(ctx).encode()) <= CONTEXT_CAP_BYTES + 200  # bounded
    assert len(ctx["top_holdings"]) < 12  # trimmed


def test_system_prompt_guardrails():
    from app.portfolio.commentary import SYSTEM_PROMPT

    assert "no trade instructions" in SYSTEM_PROMPT.lower()
    assert DISCLAIMER_LINE in SYSTEM_PROMPT
