"""FastAPI router for the ops/Tools dashboard (prefix /ops, JWT-protected)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import asyncpg
from app.ops.metrics import METRICS
from app.signals.engine import HORIZONS
from app.signals.job import SYMBOLS
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/ops", tags=["ops"])

_RESCOLS = {1: "res_1m", 5: "res_5m", 10: "res_10m", 20: "res_20m", 1440: "res_1d"}


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


async def _signal_insights(conn: asyncpg.Connection) -> dict[str, Any]:
    """Per-symbol row counts + overall backtest hit-rate per horizon."""
    per_symbol: list[dict[str, Any]] = []
    for sym in SYMBOLS:
        row = await conn.fetchrow(
            "SELECT count(*) AS n, max(ts) AS last_ts, min(ts) AS first_ts "
            "FROM spy_signals WHERE symbol = $1",
            sym,
        )
        per_symbol.append(
            {
                "symbol": sym,
                "rows": int(row["n"]) if row else 0,
                "last_ts": row["last_ts"].isoformat() if row and row["last_ts"] else None,
                "oldest_ts": row["first_ts"].isoformat() if row and row["first_ts"] else None,
            }
        )

    hit_rate: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        col = _RESCOLS[horizon]
        row = await conn.fetchrow(
            f"SELECT count(*) FILTER (WHERE {col} = 'correct') AS hits, "
            f"count(*) FILTER (WHERE {col} IN ('correct','wrong')) AS total, "
            f"count(*) FILTER (WHERE {col} IS NULL) AS pending "
            f"FROM spy_signals"
        )
        hits = int(row["hits"]) if row else 0
        total = int(row["total"]) if row else 0
        hit_rate.append(
            {
                "horizon_min": horizon,
                "hits": hits,
                "total": total,
                "pending": int(row["pending"]) if row else 0,
                "accuracy": round(hits / total, 3) if total else None,
            }
        )
    return {"per_symbol": per_symbol, "hit_rate": hit_rate}


@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    """Everything the Tools tab needs: jobs, API metrics, and signal insights."""
    snap: dict[str, Any] = METRICS.snapshot()
    async with _pool(request).acquire() as conn:
        snap["insights"] = await _signal_insights(conn)
    return snap


# ── Paper-trading reports (written by app.options_paper_job, per-day archive) ──

_REPORT_DIR = os.getenv("OPTIONS_REPORT_DIR", "/tmp/options_reports")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/paper/reports")
async def paper_reports() -> dict[str, Any]:
    """List archived paper-trading reports (one per market day) with summaries."""
    out: list[dict[str, Any]] = []
    if os.path.isdir(_REPORT_DIR):
        for name in sorted(os.listdir(_REPORT_DIR), reverse=True):
            if not name.endswith(".json") or name == "latest.json":
                continue
            date = name[:-5]
            if not _DATE_RE.match(date):
                continue
            try:
                with open(os.path.join(_REPORT_DIR, name)) as f:
                    rep = json.load(f)
                out.append(
                    {
                        "date": date,
                        "underlyings": rep.get("underlyings", []),
                        "combined": rep.get("combined", {}),
                    }
                )
            except (OSError, json.JSONDecodeError):
                continue
    return {"reports": out}


@router.get("/paper/reports/{date}")
async def paper_report(date: str) -> dict[str, Any]:
    """Full archived report for one day (YYYY-MM-DD, or 'latest')."""
    if date != "latest" and not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD or 'latest'")
    path = os.path.join(_REPORT_DIR, f"{date}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"No report for {date}")
    try:
        with open(path) as f:
            data: dict[str, Any] = json.load(f)
        return data
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Unreadable report: {exc}") from exc
