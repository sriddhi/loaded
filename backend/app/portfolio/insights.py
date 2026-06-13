"""
INSIGHTS composition: holdings × screener scores × fired macro alerts ×
upcoming earnings × health. Every section is empty-safe — missing data yields
empty lists with sane summaries, never an exception.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
from app.portfolio.health import diversification_score, run_health_checks

EARNINGS_WINDOW_DAYS = 14


async def _latest_scores(pool: asyncpg.Pool, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    rows = await pool.fetch(
        """
        SELECT e.symbol, s.composite, s.candidate, s.rank, s.reasons
        FROM screener_scores s JOIN equities e ON e.id = s.equity_id
        WHERE e.symbol = ANY($1)
          AND s.score_date = (SELECT max(score_date) FROM screener_scores)
        """,
        symbols,
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        reasons_raw = r["reasons"]
        reasons = json.loads(reasons_raw) if isinstance(reasons_raw, str) else (reasons_raw or [])
        out[r["symbol"]] = {
            "composite": float(r["composite"]) if r["composite"] is not None else None,
            "candidate": r["candidate"],
            "rank": r["rank"],
            "reasons": reasons,
        }
    return out


async def _fired_alerts(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    from app.macro.registry import ALERT_INFO

    rows = await pool.fetch(
        "SELECT alert_id, since FROM macro_alert_state WHERE fired ORDER BY alert_id"
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        info: dict[str, str] = ALERT_INFO.get(r["alert_id"], {})
        out.append(
            {
                "alert_id": r["alert_id"],
                "meaning": info.get("meaning", ""),
                "impact": info.get("impact", ""),
                "fired_since": r["since"].isoformat() if r["since"] else None,
            }
        )
    return out


async def _upcoming_earnings(
    pool: asyncpg.Pool, symbols: list[str], weights: dict[str, float]
) -> list[dict[str, Any]]:
    if not symbols:
        return []
    rows = await pool.fetch(
        """
        SELECT symbol, earnings_date, hour FROM earnings_calendar
        WHERE symbol = ANY($1)
          AND earnings_date BETWEEN CURRENT_DATE AND CURRENT_DATE + $2::int
        ORDER BY earnings_date
        """,
        symbols,
        EARNINGS_WINDOW_DAYS,
    )
    return [
        {
            "symbol": r["symbol"],
            "earnings_date": r["earnings_date"].isoformat(),
            "hour": r["hour"],
            "weight_pct": round(weights.get(r["symbol"], 0.0), 2),
        }
        for r in rows
    ]


def _macro_impacts(
    fired: list[dict[str, Any]], sector_weights: dict[str, float]
) -> list[dict[str, Any]]:
    from app.screener.scoring import SECTOR_TILT

    tilts: dict[str, dict[str, int]] = SECTOR_TILT
    out: list[dict[str, Any]] = []
    for alert in fired:
        sector_map = tilts.get(alert["alert_id"], {})
        affected = [
            {
                "sector": sector,
                "portfolio_weight_pct": round(sector_weights[sector], 2),
                "direction": "tailwind" if delta > 0 else "headwind",
            }
            for sector, delta in sector_map.items()
            if sector in sector_weights and sector_weights[sector] > 0
        ]
        if affected:
            out.append({**alert, "affected": affected})
    return out


async def build_insights(
    pool: asyncpg.Pool,
    holdings_valued: list[dict[str, Any]],
    cash_pct: float,
) -> dict[str, Any]:
    """Compose all insight sections for already-valued holdings."""
    symbols = [str(h["symbol"]) for h in holdings_valued]
    weights = {str(h["symbol"]): float(h.get("weight_pct") or 0.0) for h in holdings_valued}
    from app.screener.scoring import normalize_sector

    sector_weights: dict[str, float] = {}
    for h in holdings_valued:
        sector = str(normalize_sector(h.get("sector")) or "Unknown")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + float(h.get("weight_pct") or 0)

    scores = await _latest_scores(pool, symbols)
    sell_ranked = [
        s for s in symbols if scores.get(s, {}).get("candidate") in ("sell", "strong_sell")
    ]
    holdings_signals = {
        "summary": (
            f"{len(sell_ranked)} holding{'s' if len(sell_ranked) != 1 else ''} "
            f"now rank{'s' if len(sell_ranked) == 1 else ''} sell"
            if sell_ranked
            else "No holdings currently rank sell"
        )
        if scores
        else "No screener scores yet",
        "items": [
            {
                "symbol": s,
                "weight_pct": round(weights.get(s, 0.0), 2),
                **scores[s],
            }
            for s in symbols
            if s in scores
        ],
    }

    fired = await _fired_alerts(pool)
    checks = run_health_checks(holdings_valued, cash_pct, scores)
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "holdings_signals": holdings_signals,
        "macro_impacts": _macro_impacts(fired, sector_weights),
        "upcoming_earnings": await _upcoming_earnings(pool, symbols, weights),
        "health": {
            "diversification_score": diversification_score(holdings_valued),
            "checks": checks,
        },
    }
