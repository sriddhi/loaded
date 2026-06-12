"""FastAPI router for the macro module (prefix /macro, JWT-protected)."""

from __future__ import annotations

from typing import Any

import asyncpg
from app.macro.refresh import evaluate_now, load_all, load_series, refresh_stale
from app.macro.registry import SERIES, TRACKERS
from app.macro.signals import income_series, rolling_mean, spread, yoy
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/macro", tags=["macro"])

DISCLAIMER = "Macro trackers — informational only, not financial advice."


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _derived(data: dict[str, list[dict[str, Any]]], name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if name.endswith("_yoy") and name.removesuffix("_yoy") in data:
        out = yoy(data[name.removesuffix("_yoy")])
    elif name == "income_yoy":
        out = yoy(income_series(data.get("AWHNONAG", []), data.get("AHETPI", [])))
    elif name == "cpi_ppi_spread":
        out = spread(yoy(data.get("CPIAUCSL", [])), yoy(data.get("PPIFIS", [])))
    elif name == "icsa_4wk":
        out = rolling_mean(data.get("ICSA", []), 4)
    return out


@router.get("/trackers")
async def trackers(request: Request, points: int = Query(160, ge=10, le=600)) -> dict[str, Any]:
    """All tracker cards: raw + derived series (trimmed) + their alert states."""
    pool = _pool(request)
    data = await load_all(pool)
    alerts = {a["id"]: a for a in await evaluate_now(pool, data, include_technicals=False)}
    cards: list[dict[str, Any]] = []
    for t in TRACKERS:
        series_payload = {code: data.get(code, [])[-points:] for code in t["series"]}
        derived_payload = {name: _derived(data, name)[-points:] for name in t["derived"]}
        cards.append(
            {
                **{k: t[k] for k in ("id", "title", "note")},
                "series": series_payload,
                "derived": derived_payload,
                "alerts": [alerts[a] for a in t["alerts"] if a in alerts],
            }
        )
    freshness = await pool.fetch(
        "SELECT code, fetched_at, fred_updated_at FROM macro_series ORDER BY code"
    )
    return {
        "trackers": cards,
        "freshness": [
            {
                "code": r["code"],
                "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
                "fred_updated_at": r["fred_updated_at"],
            }
            for r in freshness
        ],
        "disclaimer": DISCLAIMER,
    }


@router.get("/alerts")
async def alerts(request: Request) -> dict[str, Any]:
    """Every alert (FRED rules + technicals) with fired state, timing + explainers."""
    all_alerts = await evaluate_now(_pool(request))
    return {
        "alerts": all_alerts,
        "fired": [a for a in all_alerts if a["fired"]],
        "disclaimer": DISCLAIMER,
    }


@router.get("/series/{code}")
async def series(
    code: str, request: Request, limit: int = Query(600, ge=1, le=5000)
) -> dict[str, Any]:
    code = code.upper()
    if code not in SERIES:
        raise HTTPException(status_code=404, detail=f"Unknown series {code}")
    points = await load_series(_pool(request), code, limit)
    return {"code": code, **SERIES[code], "points": points}


@router.post("/refresh")
async def refresh(request: Request, full: bool = Query(False)) -> dict[str, Any]:
    """Force-refresh every registry series from FRED now (full=true re-pulls all history)."""
    refreshed = await refresh_stale(_pool(request), force=True, full=full)
    return {"refreshed": refreshed, "series": len(refreshed)}
