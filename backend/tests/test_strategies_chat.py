"""Tests for the agentic strategy chat (tool-use loop + artifact typing)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.strategies import chat as chatmod  # noqa: E402
from app.strategies.models import ChatMessage  # noqa: E402


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name, tool_input, block_id="t1"):
    blk = SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)
    blk.model_dump = lambda: {"type": "tool_use", "name": name, "input": tool_input, "id": block_id}
    return blk


@pytest.mark.asyncio
async def test_chat_requires_api_key():
    with patch.dict(
        os.environ, {"ANTHROPIC_API_KEY": "", "STRATEGY_CHAT_PROVIDER": "api"}, clear=False
    ):
        assert chatmod.chat_enabled() is False
        with pytest.raises(RuntimeError):
            await chatmod.chat([ChatMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_runs_tool_then_returns_strategy_artifact():
    # First call → tool_use(propose_strategy); second call → final text.
    tool_input = {
        "name": "Breakout 20",
        "description": "20-day breakout",
        "type": "BREAKOUT",
        "parameters": {"sma_period": 20, "volume_multiplier": 1.5},
        "filters": {},
        "signal_logic": "Enter on close above the 20-day high on 1.5x volume; exit below SMA.",
    }
    resp1 = SimpleNamespace(
        stop_reason="tool_use", content=[_tool_block("propose_strategy", tool_input)]
    )
    resp2 = SimpleNamespace(stop_reason="end_turn", content=[_text_block("Here is your strategy.")])

    with (
        patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "k", "STRATEGY_CHAT_PROVIDER": "api"}, clear=False
        ),
        patch("app.strategies.chat._anthropic_call", MagicMock(side_effect=[resp1, resp2])),
    ):
        out = await chatmod.chat([ChatMessage(role="user", content="build a breakout")])

    assert out.artifact.type == "strategy"
    assert out.artifact.data["name"] == "Breakout 20"
    assert out.reply == "Here is your strategy."
    # assistant reply appended to history
    assert out.messages[-1].role == "assistant"


@pytest.mark.asyncio
async def test_chat_market_data_tool_branch():
    resp1 = SimpleNamespace(
        stop_reason="tool_use", content=[_tool_block("get_most_active", {"by": "volume", "top": 3})]
    )
    resp2 = SimpleNamespace(stop_reason="end_turn", content=[_text_block("Top names today.")])

    async def fake_tool(name, tool_input):
        from app.strategies.models import Artifact

        return "[]", Artifact(type="market_data", data={"title": "Most active", "rows": []})

    with (
        patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "k", "STRATEGY_CHAT_PROVIDER": "api"}, clear=False
        ),
        patch("app.strategies.chat._anthropic_call", MagicMock(side_effect=[resp1, resp2])),
        patch("app.strategies.chat._run_tool", AsyncMock(side_effect=fake_tool)),
    ):
        out = await chatmod.chat([ChatMessage(role="user", content="most active?")])

    assert out.artifact.type == "market_data"
    assert out.reply == "Top names today."


def test_propose_strategy_validates():
    msg, art = chatmod._tool_propose_strategy({"name": "x"})  # missing required → text/error
    assert art.type == "text"


@pytest.mark.asyncio
async def test_claude_code_provider_extracts_strategy_from_bridge():
    bridge_text = (
        "Here's a momentum strategy.\n\n"
        '```json\n{"name":"Mo","description":"d","type":"MOMENTUM",'
        '"parameters":{"sma_period":20},"filters":{},"signal_logic":"buy above sma"}\n```'
    )
    with (
        patch.dict(os.environ, {"STRATEGY_CHAT_PROVIDER": "claude_code"}, clear=False),
        patch("app.strategies.chat._bridge_chat", AsyncMock(return_value=bridge_text)),
    ):
        assert chatmod.chat_enabled() is True
        out = await chatmod.chat([ChatMessage(role="user", content="make a momentum strategy")])
    assert out.artifact.type == "strategy"
    assert out.artifact.data["name"] == "Mo"
    assert "```" not in out.reply  # json block stripped from the displayed reply


@pytest.mark.asyncio
async def test_claude_code_provider_plain_text_answer():
    with (
        patch.dict(os.environ, {"STRATEGY_CHAT_PROVIDER": "claude_code"}, clear=False),
        patch("app.strategies.chat._bridge_chat", AsyncMock(return_value="SPY is an ETF.")),
    ):
        out = await chatmod.chat([ChatMessage(role="user", content="what is SPY?")])
    assert out.artifact.type == "text"
    assert out.reply == "SPY is an ETF."
