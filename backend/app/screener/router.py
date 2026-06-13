"""FastAPI router for /screener — reads for all authed users, mutations admin-only."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from typing import Any

import asyncpg
from app.auth.security import get_current_user
from app.screener.job import LAST_RUN, SCREENER_LOCK, run_screener
from app.screener.models import (
    DISCLAIMER,
    Pillars,
    ScoreDetail,
    ScoreHistoryPoint,
    ScoreItem,
    ScoresPage,
    ScreenerStatus,
    UniverseMember,
)
from app.screener.universe import refresh_universe, universe_symbols
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter(prefix="/screener", tags=["screener"])

_SORTS = {
    "composite",
    "rank",
    "value_score",
    "quality_score",
    "growth_score",
    "momentum_score",
    "analyst_score",
    "macro_fit_score",
    "coverage",
}


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _require_admin(user: dict[str, Any]) -> None:
    if str(user.get("role")) not in ("admin", "UserRole.ADMIN"):
        raise HTTPException(status_code=403, detail="Admin only")


def _item(r: Any) -> ScoreItem:
    reasons_raw = r["reasons"]
    reasons = json.loads(reasons_raw) if isinstance(reasons_raw, str) else (reasons_raw or [])
    return ScoreItem(
        symbol=r["symbol"],
        name=r["name"],
        sector=r["sector"],
        composite=float(r["composite"]) if r["composite"] is not None else None,
        pillars=Pillars(
            value=float(r["value_score"]) if r["value_score"] is not None else None,
            quality=float(r["quality_score"]) if r["quality_score"] is not None else None,
            growth=float(r["growth_score"]) if r["growth_score"] is not None else None,
            momentum=float(r["momentum_score"]) if r["momentum_score"] is not None else None,
            analyst=float(r["analyst_score"]) if r["analyst_score"] is not None else None,
            macro_fit=float(r["macro_fit_score"]) if r["macro_fit_score"] is not None else None,
        ),
        coverage=float(r["coverage"]),
        candidate=r["candidate"],
        rank=r["rank"],
        price=(r["price_cents"] or 0) / 100 if r["price_cents"] is not None else None,
        reasons=reasons,
    )


async def _latest_date(pool: asyncpg.Pool) -> Any:
    return await pool.fetchval("SELECT max(score_date) FROM screener_scores")


@router.get("/universe", response_model=list[UniverseMember])
async def universe(
    request: Request,
    universe: str | None = Query(None, pattern="^(sp500|ndx100)$"),
    _user: Any = Depends(get_current_user),
) -> list[UniverseMember]:
    members = await universe_symbols(_pool(request), universe)
    return [
        UniverseMember(symbol=str(m["symbol"]), name=m.get("name"), sector=m.get("sector"))
        for m in members
    ]


@router.get("/scores", response_model=ScoresPage)
async def scores(
    request: Request,
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    sector: str | None = Query(None),
    candidate: str | None = Query(None),
    sort: str = Query("rank"),
    dir: str = Query("asc", pattern="^(asc|desc)$"),  # noqa: A002
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: Any = Depends(get_current_user),
) -> ScoresPage:
    pool = _pool(request)
    if sort not in _SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {sorted(_SORTS)}")
    from datetime import date as _date_cls

    raw = date or await _latest_date(pool)
    score_date: Any = _date_cls.fromisoformat(raw) if isinstance(raw, str) else raw
    if score_date is None:
        return ScoresPage(as_of=None, total=0, items=[])
    where = ["s.score_date = $1"]
    args: list[Any] = [score_date]
    if sector:
        args.append(sector)
        where.append(f"e.gics_sector = ${len(args)}")
    if candidate:
        args.append(candidate)
        where.append(f"s.candidate = ${len(args)}")
    where_sql = " AND ".join(where)
    total = await pool.fetchval(
        f"SELECT count(*) FROM screener_scores s JOIN equities e ON e.id = s.equity_id "
        f"WHERE {where_sql}",  # noqa: S608 — where built from constants
        *args,
    )
    null_sort = "NULLS LAST" if dir == "asc" else "NULLS LAST"
    rows = await pool.fetch(
        f"""
        SELECT e.symbol, e.name, e.gics_sector AS sector, s.*
        FROM screener_scores s JOIN equities e ON e.id = s.equity_id
        WHERE {where_sql}
        ORDER BY s.{sort} {dir.upper()} {null_sort}, e.symbol
        LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
        """,  # noqa: S608 — sort/dir validated against allowlists above
        *args,
        limit,
        offset,
    )
    return ScoresPage(as_of=score_date, total=int(total or 0), items=[_item(r) for r in rows])


@router.get("/scores/{symbol}", response_model=ScoreDetail)
async def score_detail(
    symbol: str,
    request: Request,
    days: int = Query(90, ge=1, le=400),
    _user: Any = Depends(get_current_user),
) -> ScoreDetail:
    pool = _pool(request)
    row = await pool.fetchrow(
        """
        SELECT e.symbol, e.name, e.gics_sector AS sector, s.*
        FROM screener_scores s JOIN equities e ON e.id = s.equity_id
        WHERE e.symbol = $1 ORDER BY s.score_date DESC LIMIT 1
        """,
        symbol.upper(),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No scores for {symbol.upper()}")
    hist = await pool.fetch(
        """
        SELECT s.score_date, s.composite, s.candidate, s.rank
        FROM screener_scores s JOIN equities e ON e.id = s.equity_id
        WHERE e.symbol = $1 ORDER BY s.score_date DESC LIMIT $2
        """,
        symbol.upper(),
        days,
    )
    base = _item(row)
    return ScoreDetail(
        **base.model_dump(),
        score_date=row["score_date"],
        history=[
            ScoreHistoryPoint(
                date=h["score_date"],
                composite=float(h["composite"]) if h["composite"] is not None else None,
                candidate=h["candidate"],
                rank=h["rank"],
            )
            for h in reversed(hist)
        ],
    )


@router.get("/candidates", response_model=ScoresPage)
async def candidates(
    request: Request,
    side: str = Query("buy", pattern="^(buy|sell)$"),
    limit: int = Query(20, ge=1, le=100),
    sector: str | None = Query(None),
    _user: Any = Depends(get_current_user),
) -> ScoresPage:
    pool = _pool(request)
    score_date = await _latest_date(pool)
    if score_date is None:
        return ScoresPage(as_of=None, total=0, items=[])
    if side == "buy":
        cands, order = ("strong_buy", "buy"), "s.rank ASC NULLS LAST"
    else:
        cands, order = ("strong_sell", "sell"), "s.rank DESC NULLS LAST"
    args: list[Any] = [score_date, list(cands)]
    where = "s.score_date = $1 AND s.candidate = ANY($2)"
    if sector:
        args.append(sector)
        where += f" AND e.gics_sector = ${len(args)}"
    rows = await pool.fetch(
        f"""
        SELECT e.symbol, e.name, e.gics_sector AS sector, s.*
        FROM screener_scores s JOIN equities e ON e.id = s.equity_id
        WHERE {where} ORDER BY {order}, e.symbol LIMIT ${len(args) + 1}
        """,  # noqa: S608 — where/order from constants
        *args,
        limit,
    )
    return ScoresPage(as_of=score_date, total=len(rows), items=[_item(r) for r in rows])


@router.get("/status", response_model=ScreenerStatus)
async def status(request: Request, _user: Any = Depends(get_current_user)) -> ScreenerStatus:
    pool = _pool(request)
    last = await _latest_date(pool)
    scored = 0
    if last is not None:
        scored = int(
            await pool.fetchval("SELECT count(*) FROM screener_scores WHERE score_date = $1", last)
            or 0
        )
    universe_count = int(
        await pool.fetchval(
            "SELECT count(DISTINCT equity_id) FROM universe_members WHERE is_current"
        )
        or 0
    )
    last_run_at = datetime.fromisoformat(LAST_RUN["at"]) if LAST_RUN.get("at") else None
    return ScreenerStatus(
        last_score_date=last,
        scored=scored,
        universe_count=universe_count,
        running=SCREENER_LOCK.locked(),
        last_run_at=last_run_at,
    )


@router.post("/run", status_code=202)
async def run_now(
    request: Request,
    budget: int | None = Query(None, ge=0, le=600),
    user: Any = Depends(get_current_user),
) -> dict[str, str]:
    _require_admin(user)
    if SCREENER_LOCK.locked():
        raise HTTPException(status_code=409, detail="Screener already running")
    pool = _pool(request)

    async def _bg() -> None:
        async with SCREENER_LOCK:
            with contextlib.suppress(Exception):
                await run_screener(pool, ingest_budget=budget)

    task = asyncio.create_task(_bg())
    request.app.state.screener_manual_task = task  # keep a reference
    return {"status": "started"}


@router.post("/universe/refresh")
async def universe_refresh(
    request: Request, user: Any = Depends(get_current_user)
) -> dict[str, int]:
    _require_admin(user)
    result: dict[str, int] = await refresh_universe(_pool(request))
    return result


__all__ = ["router", "DISCLAIMER"]
