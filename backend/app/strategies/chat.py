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
import re
from typing import Any

import anthropic
import httpx
from app.strategies.models import Artifact, ChatMessage, ChatResponse, StrategyConfig

log = logging.getLogger(__name__)

MODEL = "claude-opus-4-5"
MAX_TOOL_ITERATIONS = 5


def _provider() -> str:
    """Which chat backend to use: 'api' (Anthropic key) or 'claude_code' (bridge)."""
    return os.getenv("STRATEGY_CHAT_PROVIDER", "api").strip().lower()


def _bridge_url() -> str:
    return os.getenv("CLAUDE_BRIDGE_URL", "http://host.docker.internal:8787").rstrip("/")


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
    # claude_code uses the host bridge (subscription) — no API key required.
    if _provider() == "claude_code":
        return True
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
    """Run one chat turn. Dispatches to the configured provider."""
    if _provider() == "claude_code":
        return await _chat_claude_code(messages)
    return await _chat_api(messages)


# ── Provider: claude_code (host bridge → local subscription) ──────────────────

# Standalone prompt (does NOT inherit SYSTEM_PROMPT's tool language — in this mode
# there are no tools, so referencing them makes the model hallucinate permission
# prompts / external auth).
_CC_SYSTEM = (
    "You are Loaded's trading assistant. You explore markets and design/iterate "
    "quantitative trading strategies.\n\n"
    "MARKET DATA — you fetch it through THIS app's tools (NOT any external service, "
    "MCP, or provider; never mention permissions or connectors). To use a tool, "
    "reply with ONLY a fenced block and nothing else:\n"
    "```tool\n"
    '{"tool": "<name>", "args": { ... }}\n'
    "```\n"
    "The app runs it and replies with `TOOL RESULT (<name>): <json>`; then you "
    "continue. Available tools:\n"
    '- get_quote {"symbol":"SPY"} → latest price, day % change, day volume.\n'
    '- get_daily_history {"symbol":"SPY","days":30} → recent daily bars '
    "(date, close, volume, change_pct). Use this for volume/price-ratio questions.\n"
    '- get_most_active {"by":"volume","top":10} → today\'s most-active US equities.\n'
    '- get_fundamentals {"symbol":"AAPL"} → statements + key ratios.\n'
    "Only emit a tool block when you actually need data; once you have it, give the "
    "final answer. Do the arithmetic yourself from the returned numbers.\n\n"
    "STRATEGIES — when you propose or edit one, include a fenced ```json block: "
    "name, description, type (MOMENTUM|BREAKOUT|MEAN_REVERSION|CUSTOM), parameters "
    "(numeric defaults), filters, signal_logic (a single string: entry, exit, stop). "
    "Put a one-line summary outside the block.\n\n"
    "This is a paper-trading / indicator tool — never give personalized financial "
    "advice. Be concise."
)

# Capture a fenced JSON block (greedy inner to allow nested braces in the config).
_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_TOOL_FENCE = re.compile(r"```tool\s*(\{.*?\})\s*```", re.DOTALL)
_CC_MAX_TOOL_TURNS = 5


def _flatten(messages: list[ChatMessage]) -> str:
    lines = []
    for m in messages:
        who = "User" if m.role == "user" else "Assistant"
        lines.append(f"{who}: {m.content}")
    lines.append("Assistant:")
    return "\n\n".join(lines)


def _extract_strategy(text: str) -> Artifact | None:
    match = _FENCE.search(text)
    if not match:
        return None
    try:
        # strict=False tolerates raw newlines/tabs inside string values.
        data = json.loads(match.group(1), strict=False)
        config = StrategyConfig(**_coerce_config(data))
    except Exception:  # noqa: BLE001
        return None
    return Artifact(type="strategy", data=config.model_dump())


def _as_text(value: Any) -> str:
    """Flatten a value the model may have returned as an object/list into prose."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_as_text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "; ".join(_as_text(v) for v in value)
    return str(value)


def _coerce_config(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a loosely-shaped config dict to the StrategyConfig schema."""
    out = dict(data)
    for key in ("name", "description", "signal_logic"):
        if key in out and not isinstance(out[key], str):
            out[key] = _as_text(out[key])
    for key in ("parameters", "filters"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    return out


async def _bridge_chat(system: str, prompt: str) -> str:
    headers = {}
    token = os.getenv("CLAUDE_BRIDGE_TOKEN", "")
    if token:
        headers["X-Bridge-Token"] = token
    async with httpx.AsyncClient(timeout=200) as client:
        resp = await client.post(
            f"{_bridge_url()}/chat",
            json={"system": system, "prompt": prompt},
            headers=headers,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"claude bridge {resp.status_code}: {resp.text[:300]}")
    return str(resp.json().get("text", ""))


# ── claude_code market-data tools (app-owned; yfinance + reuse) ───────────────


def _cc_quote_sync(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period="2d", interval="1d")
    if hist is None or hist.empty:
        return {"error": f"no data for {symbol}"}
    last = hist.iloc[-1]
    prev_close = float(hist.iloc[-2]["Close"]) if len(hist) > 1 else float(last["Open"])
    close = float(last["Close"])
    change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0
    return {
        "symbol": symbol.upper(),
        "price": round(close, 2),
        "day_change_pct": round(change_pct, 3),
        "day_volume": int(last["Volume"] or 0),
    }


def _cc_history_sync(symbol: str, days: int) -> dict[str, Any]:
    import yfinance as yf

    days = max(2, min(int(days), 400))
    hist = yf.Ticker(symbol).history(period=f"{days + 5}d", interval="1d")
    if hist is None or hist.empty:
        return {"error": f"no data for {symbol}"}
    hist = hist.tail(days)
    closes = hist["Close"].astype(float)
    pct = closes.pct_change().fillna(0.0) * 100
    rows = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "close": round(float(c), 2),
            "volume": int(v or 0),
            "change_pct": round(float(p), 3),
        }
        for idx, c, v, p in zip(hist.index, closes, hist["Volume"], pct, strict=False)
    ]
    return {"symbol": symbol.upper(), "days": len(rows), "bars": rows}


async def _cc_run_tool(name: str, args: dict[str, Any]) -> tuple[str, Artifact | None]:
    try:
        if name == "get_quote":
            data = await asyncio.to_thread(_cc_quote_sync, args["symbol"])
            return json.dumps(data), Artifact(
                type="market_data",
                data={"title": f"{args['symbol'].upper()} quote", "rows": [data]},
            )
        if name == "get_daily_history":
            data = await asyncio.to_thread(_cc_history_sync, args["symbol"], args.get("days", 30))
            return json.dumps(data), Artifact(
                type="market_data",
                data={
                    "title": f"{args['symbol'].upper()} · {data.get('days', 0)}d history",
                    "rows": data.get("bars", [])[-12:],
                },
            )
        if name == "get_most_active":
            return await _tool_most_active(args.get("by", "volume"), args.get("top", 10))
        if name == "get_fundamentals":
            return await _tool_fundamentals(args["symbol"])
        return json.dumps({"error": f"unknown tool {name}"}), None
    except Exception as exc:  # noqa: BLE001
        log.warning("[chat:cc] tool %s failed: %s", name, exc)
        return json.dumps({"error": str(exc)}), None


async def _chat_claude_code(messages: list[ChatMessage]) -> ChatResponse:
    prompt = _flatten(messages)
    artifact: Artifact | None = None
    text = ""
    for _ in range(_CC_MAX_TOOL_TURNS):
        text = await _bridge_chat(_CC_SYSTEM, prompt)
        tool_match = _TOOL_FENCE.search(text)
        if not tool_match:
            break
        try:
            call = json.loads(tool_match.group(1), strict=False)
            result, art = await _cc_run_tool(call.get("tool", ""), call.get("args", {}) or {})
        except Exception as exc:  # noqa: BLE001
            result, art = json.dumps({"error": str(exc)}), None
        if art is not None:
            artifact = art
        # Feed the tool result back and let the model continue.
        prompt += f"\n\n{text}\n\nTOOL RESULT ({call.get('tool', '')}): {result}\n\nAssistant:"

    strategy = _extract_strategy(text)
    if strategy is not None:
        artifact = strategy
    reply = _FENCE.sub("", text).strip()
    if artifact is None:
        artifact = Artifact(type="text", data=reply)
    out = list(messages) + [ChatMessage(role="assistant", content=reply)]
    return ChatResponse(reply=reply, messages=out, artifact=artifact)


# ── Provider: api (Anthropic key + agentic tool loop) ─────────────────────────


async def _chat_api(messages: list[ChatMessage]) -> ChatResponse:
    """Run one chat turn with the internal tool-use loop (Anthropic API key)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
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
