"""
AI advisor commentary — daily cached, server-built context only.

The prompt is assembled entirely from DB-derived JSON (no user free-text path),
dispatched through the same provider contract as the strategies chat
(STRATEGY_CHAT_PROVIDER: claude_code → local bridge, else Anthropic API), and
cached per UTC day in agent_models. The disclaimer is enforced server-side.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

DISCLAIMER_LINE = "Heuristic, educational — not financial advice."
AGENT_TYPE = "portfolio_commentary"
CONTEXT_CAP_BYTES = 4096
MAX_TOKENS = 900

SYSTEM_PROMPT = (
    "You are an educational portfolio review assistant for a young retail "
    "audience. Write a markdown review (max ~400 words) of the portfolio "
    "context JSON the user message contains. Plain language, short sections: "
    "what the portfolio looks like, what stands out (concentration, scores, "
    "macro backdrop, upcoming earnings), and what a professional would watch "
    "next. Explain WHY using only the provided numbers — never invent data. "
    "Strictly no trade instructions, no price targets, no 'you should buy/"
    "sell'. End with exactly this line: " + DISCLAIMER_LINE
)


class CommentaryUnavailableError(RuntimeError):
    """Provider missing or failed — surfaced as 503, never cached."""


def _provider() -> str:
    return os.getenv("STRATEGY_CHAT_PROVIDER", "api").strip().lower()


def build_context(
    portfolio: dict[str, Any],
    holdings_valued: list[dict[str, Any]],
    insights: dict[str, Any],
    performance: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compact server-built JSON context, capped at ~4KB."""
    top = sorted(holdings_valued, key=lambda h: -(h.get("market_value") or 0))[:12]
    score_by_symbol = {
        i["symbol"]: {"candidate": i.get("candidate"), "composite": i.get("composite")}
        for i in insights.get("holdings_signals", {}).get("items", [])
    }
    ctx: dict[str, Any] = {
        "portfolio": {
            "name": portfolio.get("name"),
            "kind": portfolio.get("kind"),
            "total_value": portfolio.get("total_value"),
            "cash": portfolio.get("cash"),
        },
        "top_holdings": [
            {
                "symbol": h["symbol"],
                "weight_pct": h.get("weight_pct"),
                "unrealized_pct": h.get("unrealized_pct"),
                **score_by_symbol.get(str(h["symbol"]), {}),
            }
            for h in top
        ],
        "performance": {
            k: (performance or {}).get(k) for k in ("twr_pct", "simple_return_pct", "beta")
        },
        "health": {
            "diversification_score": insights.get("health", {}).get("diversification_score"),
            "issues": [
                {"id": c["id"], "status": c["status"], "detail": c["detail"]}
                for c in insights.get("health", {}).get("checks", [])
                if c["status"] != "ok"
            ],
        },
        "fired_macro_alerts": [
            {"id": m["alert_id"], "meaning": m["meaning"]}
            for m in insights.get("macro_impacts", [])
        ],
        "upcoming_earnings": insights.get("upcoming_earnings", []),
    }
    raw = json.dumps(ctx)
    while len(raw.encode()) > CONTEXT_CAP_BYTES and ctx["top_holdings"]:
        ctx["top_holdings"] = ctx["top_holdings"][:-1]  # trim until under cap
        raw = json.dumps(ctx)
    return ctx


def _anthropic_commentary(context_json: str) -> str:
    import anthropic
    from app.strategies.chat import MODEL

    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise CommentaryUnavailableError("ANTHROPIC_API_KEY not configured")
    client = anthropic.Anthropic(api_key=key)
    model: str = MODEL
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_json}],
    )
    parts = [str(getattr(b, "text", "")) for b in resp.content if getattr(b, "type", "") == "text"]
    return "\n".join(parts).strip()


async def _generate_markdown(context: dict[str, Any]) -> str:
    context_json = json.dumps(context, indent=1)
    if _provider() == "claude_code":
        from app.strategies.chat import _bridge_chat

        try:
            text: str = await _bridge_chat(SYSTEM_PROMPT, context_json)
        except Exception as exc:  # noqa: BLE001
            raise CommentaryUnavailableError(f"bridge failed: {exc}") from exc
    else:
        try:
            text = await asyncio.to_thread(_anthropic_commentary, context_json)
        except CommentaryUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CommentaryUnavailableError(f"provider failed: {exc}") from exc
    if not text.strip():
        raise CommentaryUnavailableError("provider returned empty commentary")
    if DISCLAIMER_LINE not in text:
        text = f"{text.rstrip()}\n\n{DISCLAIMER_LINE}"
    return text


async def get_cached(pool: asyncpg.Pool, owner_id: int, portfolio_id: int) -> dict[str, Any] | None:
    """Today's latest cached commentary, or None."""
    row = await pool.fetchrow(
        """
        SELECT analysis, version, data_as_of FROM agent_models
        WHERE agent_type = $1 AND entity_key = $2
          AND data_as_of::date = CURRENT_DATE
        ORDER BY version DESC LIMIT 1
        """,
        AGENT_TYPE,
        f"{owner_id}:{portfolio_id}",
    )
    if row is None:
        return None
    analysis = row["analysis"]
    data = analysis if isinstance(analysis, dict) else json.loads(analysis)
    return {
        "markdown": data.get("markdown", ""),
        "generated_at": row["data_as_of"].isoformat(),
        "version": int(row["version"]),
    }


async def generate(
    pool: asyncpg.Pool,
    owner_id: int,
    portfolio_id: int,
    context: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Cached-per-day generation; force regenerates and bumps the version."""
    if not force:
        cached = await get_cached(pool, owner_id, portfolio_id)
        if cached is not None:
            return {**cached, "cached": True}
    markdown = await _generate_markdown(context)
    entity_key = f"{owner_id}:{portfolio_id}"
    now = datetime.now(UTC)
    async with pool.acquire() as conn:
        version = await conn.fetchval(
            "SELECT COALESCE(max(version), 0) + 1 FROM agent_models "
            "WHERE agent_type = $1 AND entity_key = $2",
            AGENT_TYPE,
            entity_key,
        )
        await conn.execute(
            """
            INSERT INTO agent_models (agent_type, entity_key, version, model_schema,
                                      analysis, supporting_data, predictions,
                                      explanation, data_as_of)
            VALUES ($1, $2, $3, '{}'::jsonb, $4, $5, '{}'::jsonb, $6, $7)
            """,
            AGENT_TYPE,
            entity_key,
            int(version or 1),
            json.dumps({"markdown": markdown}),
            json.dumps(context),
            markdown,
            now,
        )
    return {
        "markdown": markdown,
        "generated_at": now.isoformat(),
        "version": int(version or 1),
        "cached": False,
    }
