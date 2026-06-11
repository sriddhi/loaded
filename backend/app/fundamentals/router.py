"""FastAPI router for the fundamentals module (prefix /fundamentals, JWT-protected)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import asyncpg
from app.fundamentals.forward import forward_metrics
from app.fundamentals.ingest import ingest_statements
from app.fundamentals.metrics import FundamentalMetrics, MetricContext, available_metrics, to_ttm
from app.fundamentals.models import (
    EquityFinancials,
    ForwardResponse,
    MetricsResponse,
    PeriodType,
    PriceResponse,
    RefreshResult,
    StatementsResponse,
    TrackedEquity,
)
from app.fundamentals.price_cache import PriceStore
from app.fundamentals.price_fallback import resolve_price
from app.fundamentals.refresh import ensure_fresh
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


async def _as_of(conn: asyncpg.Connection, symbol: str) -> datetime | None:
    val: datetime | None = await conn.fetchval(
        "SELECT MAX(fs.fetched_at) FROM financial_statements fs "
        "JOIN equities e ON fs.equity_id = e.id WHERE e.symbol = $1",
        symbol.upper(),
    )
    return val


async def _refresh_then_track(request: Request, symbol: str) -> None:
    """Lazy-TTL freshness before a read; cold start blocks, stale serves+refreshes."""
    pool = _pool(request)
    async with pool.acquire() as conn:
        tracked = bool(
            await conn.fetchval("SELECT is_tracked FROM equities WHERE symbol = $1", symbol.upper())
        )
    try:
        await ensure_fresh(pool, symbol, tracked=tracked)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Tracklist ─────────────────────────────────────────────────────────────────


@router.get("/tracked", response_model=list[TrackedEquity])
async def list_tracked(request: Request) -> list[TrackedEquity]:
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            "SELECT symbol, name, gics_sector, market_cap_tier "
            "FROM equities WHERE is_tracked = TRUE ORDER BY symbol"
        )
    return [
        TrackedEquity(
            symbol=r["symbol"],
            name=r["name"],
            sector=r["gics_sector"],
            market_cap_tier=r["market_cap_tier"],
        )
        for r in rows
    ]


@router.post("/tracked/{symbol}", response_model=TrackedEquity, status_code=201)
async def add_tracked(symbol: str, request: Request) -> TrackedEquity:
    """Add a ticker to the fundamentals tracklist: ingest its statements + flag tracked."""
    symbol = symbol.upper()
    try:
        async with _pool(request).acquire() as conn:
            await ingest_statements(symbol, conn)  # creates/updates the equity row
            row = await conn.fetchrow(
                "UPDATE equities SET is_tracked = TRUE WHERE symbol = $1 "
                "RETURNING symbol, name, gics_sector, market_cap_tier",
                symbol,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equity not found")
    return TrackedEquity(
        symbol=row["symbol"],
        name=row["name"],
        sector=row["gics_sector"],
        market_cap_tier=row["market_cap_tier"],
    )


@router.delete("/tracked/{symbol}", status_code=204)
async def remove_tracked(symbol: str, request: Request) -> None:
    async with _pool(request).acquire() as conn:
        await conn.execute(
            "UPDATE equities SET is_tracked = FALSE WHERE symbol = $1", symbol.upper()
        )


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
    await _refresh_then_track(request, symbol)
    async with _pool(request).acquire() as conn:
        series = await _load_series(conn, symbol, period_type)
        as_of = await _as_of(conn, symbol)
    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No statements for {symbol.upper()} — run refresh first",
        )
    return StatementsResponse(
        symbol=symbol.upper(), period_type=period, statements=series, as_of=as_of
    )


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
    await _refresh_then_track(request, symbol)
    async with _pool(request).acquire() as conn:
        series = await _load_series(conn, symbol, load_type)
        as_of = await _as_of(conn, symbol)
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
    resolved = await resolve_price(symbol, _price_cache(request))
    if resolved is not None:
        price_used = resolved[0]

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
        as_of=as_of,
    )


@router.get("/{symbol}/price", response_model=PriceResponse)
async def price(symbol: str, request: Request) -> PriceResponse:
    resolved = await resolve_price(symbol, _price_cache(request))
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="price unavailable: no live tick and REST quote failed",
        )
    px, ts_ms, source = resolved
    now_ms = int(time.time() * 1000)
    # A websocket tick goes stale after STALE_AFTER_MS; a REST quote is fresh now.
    stale = source == "websocket" and (now_ms - ts_ms) > STALE_AFTER_MS
    return PriceResponse(
        symbol=symbol.upper(),
        price=px,
        ts=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
        stale=stale,
    )


@router.get("/{symbol}/forward", response_model=ForwardResponse)
async def forward(symbol: str, request: Request) -> ForwardResponse:
    """Forward P/E at the current price — deterministic; null fields when no estimate."""
    resolved = await resolve_price(symbol, _price_cache(request))
    px = resolved[0] if resolved is not None else None
    fwd = await forward_metrics(symbol, px)
    return ForwardResponse(
        symbol=symbol.upper(),
        price=px,
        forward_eps=fwd["forward_eps"],
        trailing_eps=fwd["trailing_eps"],
        forward_pe=fwd["forward_pe"],
    )
