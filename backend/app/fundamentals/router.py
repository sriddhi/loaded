"""FastAPI router for the fundamentals module (prefix /fundamentals, JWT-protected)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import asyncpg
from app.fundamentals.ingest import ingest_statements
from app.fundamentals.metrics import FundamentalMetrics, MetricContext, available_metrics, to_ttm
from app.fundamentals.models import (
    EquityFinancials,
    MetricsResponse,
    PeriodType,
    PriceResponse,
    RefreshResult,
    StatementsResponse,
)
from app.fundamentals.price_cache import PriceStore
from fastapi import APIRouter, HTTPException, Query, Request, status

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])

STALE_AFTER_MS = 60_000

# EquityFinancials fields populated from a financial_statements row.
_MODEL_FIELDS = [
    "asset_class",
    "period_type",
    "period_end",
    "fiscal_year",
    "fiscal_quarter",
    "currency",
    "source",
    "revenue",
    "cogs",
    "gross_profit",
    "operating_income",
    "net_income",
    "ebitda",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "total_debt",
    "cash_and_equiv",
    "current_assets",
    "current_liabilities",
    "inventory",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "eps_basic",
    "eps_diluted",
    "shares_basic",
    "shares_diluted",
    "shares_outstanding",
    "dividends_paid",
]


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _price_cache(request: Request) -> PriceStore | None:
    return getattr(request.app.state, "price_cache", None)


def _row_to_equity(row: asyncpg.Record) -> EquityFinancials:
    data: dict[str, Any] = {"symbol": row["symbol"]}
    for f in _MODEL_FIELDS:
        data[f] = row[f]
    return EquityFinancials(**data)


async def _load_series(
    conn: asyncpg.Connection, symbol: str, period_type: str
) -> list[EquityFinancials]:
    rows = await conn.fetch(
        """
        SELECT fs.*, e.symbol AS symbol
        FROM financial_statements fs
        JOIN equities e ON fs.equity_id = e.id
        WHERE e.symbol = $1 AND fs.period_type = $2
        ORDER BY fs.period_end DESC
        """,
        symbol.upper(),
        period_type,
    )
    return [_row_to_equity(r) for r in rows]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/{symbol}/refresh", response_model=RefreshResult)
async def refresh(symbol: str, request: Request) -> RefreshResult:
    try:
        async with _pool(request).acquire() as conn:
            result = await ingest_statements(symbol.upper(), conn)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RefreshResult(**result)


@router.get("/{symbol}/statements", response_model=StatementsResponse)
async def statements(
    symbol: str,
    request: Request,
    period: PeriodType = Query("annual"),
    type: str = Query("all"),  # noqa: A002 — API surface name
) -> StatementsResponse:
    period_type = "quarterly" if period == "quarterly" else "annual"
    async with _pool(request).acquire() as conn:
        series = await _load_series(conn, symbol, period_type)
    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No statements for {symbol.upper()} — run refresh first",
        )
    return StatementsResponse(symbol=symbol.upper(), period_type=period, statements=series)


@router.get("/{symbol}/metrics", response_model=MetricsResponse)
async def metrics(
    symbol: str,
    request: Request,
    metrics: str = Query(..., description="comma-separated metric names"),
    period: PeriodType = Query("annual"),
) -> MetricsResponse:
    requested = [m.strip() for m in metrics.split(",") if m.strip()]
    if not requested:
        raise HTTPException(status_code=422, detail="No metrics requested")

    load_type = "annual" if period == "annual" else "quarterly"
    async with _pool(request).acquire() as conn:
        series = await _load_series(conn, symbol, load_type)
    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No statements for {symbol.upper()} — run refresh first",
        )

    if period == "ttm":
        latest: EquityFinancials | None = to_ttm(list(series))
    else:
        latest = series[0]

    price_used: float | None = None
    cache = _price_cache(request)
    if cache is not None:
        hit = cache.get(symbol)
        if hit is not None:
            price_used = hit[0]

    ctx = MetricContext(
        latest=latest, series=list(series), period_type=period, live_price=price_used
    )
    computed, unknown = FundamentalMetrics(ctx).compute(requested)
    # Fully-unknown request (typo) → 422; partial unknowns reported in the body.
    if unknown and not computed:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown metrics: {', '.join(unknown)}. Available: {', '.join(available_metrics())}",
        )
    return MetricsResponse(
        symbol=symbol.upper(),
        period=period,
        metrics=computed,
        price_used=price_used,
        unknown_metrics=unknown,
    )


@router.get("/{symbol}/price", response_model=PriceResponse)
async def price(symbol: str, request: Request) -> PriceResponse:
    cache = _price_cache(request)
    hit = cache.get(symbol) if cache is not None else None
    if hit is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="price unavailable: websocket not connected or no tick yet",
        )
    px, ts_ms = hit
    now_ms = int(time.time() * 1000)
    return PriceResponse(
        symbol=symbol.upper(),
        price=px,
        ts=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
        stale=(now_ms - ts_ms) > STALE_AFTER_MS,
    )
