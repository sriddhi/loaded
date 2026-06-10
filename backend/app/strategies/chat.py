"""
Agentic chat assistant for Strategy Lab — a market-aware strategy builder.

It answers market/data questions (most-active equities, movers, quotes,
fundamentals) AND designs/edits StrategyConfigs, using Anthropic tool use. Each
turn returns a reply plus a typed `artifact` that drives the right-hand panel.

Read-only: it never places trades and never mutates the DB. The only "action"
tool is `propose_strategy`, which just emits a validated config for the UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import anthropic
from app.strategies.models import Artifact, ChatMessage, ChatResponse, StrategyConfig

log = logging.getLogger(__name__)

MODEL = "claude-opus-4-5"
MAX_TOOL_ITERATIONS = 5

SYSTEM_PROMPT = """You are Loaded's trading assistant. You help users explore the \
market and design/iterate quantitative trading strategies.

Capabilities:
- Answer market questions using your tools (most-active equities, market movers, \
quotes, company fundamentals). Always call a tool for live data — never guess \
numbers.
- Design or edit a trading strategy. When the user wants a strategy (or asks to \
change one), call `propose_strategy` with a COMPLETE config: every numeric \
parameter has a concrete default; signal_logic states the exact entry trigger, \
exit trigger, and any stop-loss.

Rules:
- This is a paper-trading / indicator tool. You never execute trades and you do \
not give personalized financial advice.
- Be concise. After a tool call, briefly summarize what you found or built.
"""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_most_active",
        "description": "Most actively traded US equities today, by volume or trade count.",
        "input_schema": {
            "type": "object",
            "properties": {
                "by": {"type": "string", "enum": ["volume", "trades"]},
                "top": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_market_movers",
        "description": "Top market gainers and losers today.",
        "input_schema": {
            "type": "object",
            "properties": {"top": {"type": "integer"}},
        },
    },
    {
        "name": "get_quote",
        "description": "Latest quote (price) for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_fundamentals",
        "description": "Company fundamentals (financial statements + key ratios) for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "propose_strategy",
        "description": "Emit a complete trading strategy config to show the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["MOMENTUM", "BREAKOUT", "MEAN_REVERSION", "CUSTOM"],
                },
                "parameters": {"type": "object"},
                "filters": {"type": "object"},
                "signal_logic": {"type": "string"},
            },
            "required": ["name", "description", "type", "signal_logic"],
        },
    },
]


def chat_enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# ── Tool execution (read-only) ────────────────────────────────────────────────


async def _tool_most_active(by: str = "volume", top: int = 10) -> tuple[str, Artifact]:
    def _call() -> list[dict[str, Any]]:
        from alpaca.data.enums import MostActivesBy
        from alpaca.data.requests import MostActivesRequest
        from app.marketdata.client import get_screener_client

        by_enum = MostActivesBy.TRADES if by == "trades" else MostActivesBy.VOLUME
        result = get_screener_client().get_most_actives(MostActivesRequest(top=top, by=by_enum))
        return [
            {
                "symbol": a.symbol,
                "volume": getattr(a, "volume", None),
                "trades": getattr(a, "trade_count", None),
            }
            for a in getattr(result, "most_actives", [])
        ]

    rows = await asyncio.to_thread(_call)
    data = {"title": f"Most active by {by}", "rows": rows}
    return json.dumps(rows), Artifact(type="market_data", data=data)


async def _tool_market_movers(top: int = 10) -> tuple[str, Artifact]:
    def _call() -> dict[str, Any]:
        from alpaca.data.enums import MarketType
        from alpaca.data.requests import MarketMoversRequest
        from app.marketdata.client import get_screener_client

        result = get_screener_client().get_market_movers(
            MarketMoversRequest(market_type=MarketType.STOCKS, top=top)
        )

        def fmt(lst: Any) -> list[dict[str, Any]]:
            return [
                {
                    "symbol": m.symbol,
                    "percent_change": getattr(m, "percent_change", None),
                    "price": getattr(m, "price", None),
                }
                for m in lst
            ]

        return {
            "gainers": fmt(getattr(result, "gainers", [])),
            "losers": fmt(getattr(result, "losers", [])),
        }

    data = await asyncio.to_thread(_call)
    return json.dumps(data), Artifact(type="market_data", data={"title": "Market movers", **data})


async def _tool_quote(symbol: str) -> tuple[str, Artifact]:
    def _call() -> dict[str, Any]:
        from alpaca.data.requests import StockLatestQuoteRequest
        from app.marketdata.client import get_stock_client

        q = get_stock_client().get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol)
        )[symbol]
        return {
            "symbol": symbol,
            "bid": getattr(q, "bid_price", None),
            "ask": getattr(q, "ask_price", None),
        }

    data = await asyncio.to_thread(_call)
    return json.dumps(data), Artifact(
        type="market_data", data={"title": f"{symbol} quote", "rows": [data]}
    )


async def _tool_fundamentals(symbol: str) -> tuple[str, Artifact]:
    from app.agents.data import fetch_fundamentals

    data = await fetch_fundamentals(symbol)
    summary = {k: data.get(k) for k in ("symbol", "name", "ratios") if k in data}
    return json.dumps(summary, default=str)[:4000], Artifact(
        type="market_data", data={"title": f"{symbol} fundamentals", "fundamentals": summary}
    )


def _tool_propose_strategy(tool_input: dict[str, Any]) -> tuple[str, Artifact]:
    try:
        config = StrategyConfig(**tool_input)
    except Exception as exc:  # noqa: BLE001
        return f"Invalid strategy config: {exc}", Artifact(type="text", data=str(exc))
    return (
        f"Proposed strategy '{config.name}'.",
        Artifact(type="strategy", data=config.model_dump()),
    )


async def _run_tool(name: str, tool_input: dict[str, Any]) -> tuple[str, Artifact | None]:
    try:
        if name == "get_most_active":
            return await _tool_most_active(
                tool_input.get("by", "volume"), tool_input.get("top", 10)
            )
        if name == "get_market_movers":
            return await _tool_market_movers(tool_input.get("top", 10))
        if name == "get_quote":
            return await _tool_quote(tool_input["symbol"])
        if name == "get_fundamentals":
            return await _tool_fundamentals(tool_input["symbol"])
        if name == "propose_strategy":
            return _tool_propose_strategy(tool_input)
        return f"Unknown tool: {name}", None
    except Exception as exc:  # noqa: BLE001
        log.warning("[chat] tool %s failed: %s", name, exc)
        return (
            f"Tool '{name}' failed: {exc}. (Live market tools may require Alpaca API keys.)",
            None,
        )


# ── Agentic loop ──────────────────────────────────────────────────────────────


def _to_api_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _anthropic_call(api_messages: list[dict[str, Any]]) -> Any:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=TOOLS,  # type: ignore[arg-type]
        messages=api_messages,  # type: ignore[arg-type]
    )


async def chat(messages: list[ChatMessage]) -> ChatResponse:
    """Run one chat turn (with an internal tool-use loop). Returns reply + artifact."""
    if not chat_enabled():
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    working = _to_api_messages(messages)
    artifact = Artifact(type="text", data=None)
    reply_text = ""

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = await asyncio.to_thread(_anthropic_call, working)
        text_parts = [b.text for b in resp.content if b.type == "text"]
        if text_parts:
            reply_text = "\n".join(text_parts).strip()

        if resp.stop_reason != "tool_use":
            break

        # Append the assistant's tool-use turn, then run tools and feed results back.
        working.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        tool_results: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            result_str, art = await _run_tool(block.name, dict(block.input))
            if art is not None:
                artifact = art
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
            )
        working.append({"role": "user", "content": tool_results})

    out_messages = list(messages) + [ChatMessage(role="assistant", content=reply_text)]
    return ChatResponse(reply=reply_text, messages=out_messages, artifact=artifact)
