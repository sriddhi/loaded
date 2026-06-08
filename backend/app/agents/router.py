from __future__ import annotations

import asyncio

import asyncpg
from app.agents.ingest import ingest_fundamentals
from app.agents.models import (
    AnalystData,
    BatchIngestRequest,
    BatchIngestResponse,
    EquityMeta,
    FundamentalPeriod,
    FundamentalsResponse,
    IngestResult,
    RatiosData,
    SearchResult,
)
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["agents"])


def _pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


# ── Ingest ────────────────────────────────────────────────────────────────────


@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch(body: BatchIngestRequest, request: Request) -> BatchIngestResponse:
    """Concurrently fetch + store fundamentals for a list of tickers."""
    pool = _pool(request)

    async def _one(symbol: str) -> IngestResult:
        sym = symbol.upper()
        try:
            async with pool.acquire() as conn:
                result = await ingest_fundamentals(sym, conn)
            return IngestResult(status="ok", **result)
        except ValueError as e:
            return IngestResult(symbol=sym, status="error", error=str(e))
        except Exception as e:
            return IngestResult(symbol=sym, status="error", error=str(e))

    results = await asyncio.gather(*[_one(s) for s in body.symbols])
    return BatchIngestResponse(results=list(results))


@router.post("/ingest/{symbol}", response_model=IngestResult)
async def ingest_symbol(symbol: str, request: Request) -> IngestResult:
    """Fetch + store all fundamentals for a single ticker."""
    symbol = symbol.upper()
    try:
        async with _pool(request).acquire() as conn:
            result = await ingest_fundamentals(symbol, conn)
        return IngestResult(status="ok", **result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e}") from e


# ── Query ─────────────────────────────────────────────────────────────────────


@router.get("/equity/{symbol}", response_model=EquityMeta)
async def get_equity(symbol: str, request: Request) -> EquityMeta:
    """Return equity metadata for a ticker."""
    symbol = symbol.upper()
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(
            "SELECT symbol, name, exchange, gics_sector, gics_industry, market_cap_tier, is_tracked FROM equities WHERE symbol=$1",
            symbol,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Equity not found: {symbol}")
    return EquityMeta(
        symbol=row["symbol"],
        name=row["name"],
        exchange=row["exchange"],
        sector=row["gics_sector"],
        industry=row["gics_industry"],
        market_cap_tier=row["market_cap_tier"],
        is_tracked=row["is_tracked"],
    )


@router.get("/fundamentals/{symbol}", response_model=FundamentalsResponse)
async def get_fundamentals(symbol: str, request: Request) -> FundamentalsResponse:
    """Return structured fundamentals (annual + quarterly + ratios + analyst)."""
    symbol = symbol.upper()
    pool = _pool(request)

    async with pool.acquire() as conn:
        equity_row = await conn.fetchrow(
            "SELECT id, symbol, name, exchange, gics_sector, gics_industry, market_cap_tier, is_tracked FROM equities WHERE symbol=$1",
            symbol,
        )
        if not equity_row:
            raise HTTPException(status_code=404, detail=f"Equity not found: {symbol}")

        equity_id = equity_row["id"]

        fund_rows = await conn.fetch(
            """
            SELECT * FROM fundamentals
            WHERE equity_id = $1
            ORDER BY period_end DESC
            """,
            equity_id,
        )

        analyst_row = await conn.fetchrow(
            """
            SELECT * FROM analyst_estimates
            WHERE equity_id = $1
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            equity_id,
        )

    annual = [_row_to_period(r) for r in fund_rows if r["period_type"] == "annual"][:4]
    quarterly = [_row_to_period(r) for r in fund_rows if r["period_type"] == "quarterly"][:8]

    # Ratios: pull from most recent quarterly, fall back to annual
    ratio_source = quarterly[0] if quarterly else (annual[0] if annual else None)
    ratios = (
        _extract_ratios(ratio_source)
        if ratio_source
        else RatiosData(
            pe_ratio=None,
            pb_ratio=None,
            ps_ratio=None,
            ev_ebitda=None,
            ev_revenue=None,
            gross_margin=None,
            operating_margin=None,
            net_margin=None,
            roe=None,
            roic=None,
            debt_to_equity=None,
            revenue_growth_yoy=None,
        )
    )

    analyst = _row_to_analyst(analyst_row) if analyst_row else None
    fetched_at = fund_rows[0]["fetched_at"] if fund_rows else None

    equity_meta = EquityMeta(
        symbol=equity_row["symbol"],
        name=equity_row["name"],
        exchange=equity_row["exchange"],
        sector=equity_row["gics_sector"],
        industry=equity_row["gics_industry"],
        market_cap_tier=equity_row["market_cap_tier"],
        is_tracked=equity_row["is_tracked"],
    )

    return FundamentalsResponse(
        equity=equity_meta,
        annual=annual,
        quarterly=quarterly,
        ratios=ratios,
        analyst=analyst,
        fetched_at=fetched_at,
    )


@router.get("/search", response_model=list[SearchResult])
async def search_equities(q: str, request: Request) -> list[SearchResult]:
    """Fuzzy search equities by symbol or company name."""
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, name, gics_sector, market_cap_tier, is_tracked
            FROM equities
            WHERE symbol ILIKE $1 OR name ILIKE $1
            ORDER BY is_tracked DESC, symbol
            LIMIT 10
            """,
            f"%{q}%",
        )
    return [
        SearchResult(
            symbol=r["symbol"],
            name=r["name"],
            sector=r["gics_sector"],
            market_cap_tier=r["market_cap_tier"],
            is_tracked=r["is_tracked"],
        )
        for r in rows
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cents_to_dollars(value: int | None) -> float | None:
    """Money is stored as integer cents; the API contract is US dollars."""
    if value is None:
        return None
    return round(value / 100, 2)


def _row_to_period(row: asyncpg.Record) -> FundamentalPeriod:
    return FundamentalPeriod(
        period_type=row["period_type"],
        period_end=row["period_end"],
        fiscal_year=row["fiscal_year"],
        fiscal_quarter=row["fiscal_quarter"],
        revenue=_cents_to_dollars(row["revenue"]),
        gross_profit=_cents_to_dollars(row["gross_profit"]),
        operating_income=_cents_to_dollars(row["operating_income"]),
        net_income=_cents_to_dollars(row["net_income"]),
        ebitda=_cents_to_dollars(row["ebitda"]),
        eps_basic=row["eps_basic"],
        eps_diluted=row["eps_diluted"],
        shares_basic=row["shares_basic"],
        shares_diluted=row["shares_diluted"],
        cash_and_equiv=_cents_to_dollars(row["cash_and_equiv"]),
        total_assets=_cents_to_dollars(row["total_assets"]),
        total_liabilities=_cents_to_dollars(row["total_liabilities"]),
        total_equity=_cents_to_dollars(row["total_equity"]),
        total_debt=_cents_to_dollars(row["total_debt"]),
        net_debt=_cents_to_dollars(row["net_debt"]),
        operating_cash_flow=_cents_to_dollars(row["operating_cash_flow"]),
        capex=_cents_to_dollars(row["capex"]),
        free_cash_flow=_cents_to_dollars(row["free_cash_flow"]),
        dividends_paid=_cents_to_dollars(row["dividends_paid"]),
        gross_margin=float(row["gross_margin"]) if row["gross_margin"] is not None else None,
        operating_margin=float(row["operating_margin"])
        if row["operating_margin"] is not None
        else None,
        net_margin=float(row["net_margin"]) if row["net_margin"] is not None else None,
        roe=float(row["roe"]) if row["roe"] is not None else None,
        roa=float(row["roa"]) if row["roa"] is not None else None,
        roic=float(row["roic"]) if row["roic"] is not None else None,
        debt_to_equity=float(row["debt_to_equity"]) if row["debt_to_equity"] is not None else None,
        revenue_growth_yoy=float(row["revenue_growth_yoy"])
        if row["revenue_growth_yoy"] is not None
        else None,
        eps_growth_yoy=float(row["eps_growth_yoy"]) if row["eps_growth_yoy"] is not None else None,
        price_at_fetch=float(row["price_at_fetch"]) if row["price_at_fetch"] is not None else None,
        market_cap=_cents_to_dollars(row["market_cap"]),
        pe_ratio=float(row["pe_ratio"]) if row["pe_ratio"] is not None else None,
        pb_ratio=float(row["pb_ratio"]) if row["pb_ratio"] is not None else None,
        ps_ratio=float(row["ps_ratio"]) if row["ps_ratio"] is not None else None,
        ev_ebitda=float(row["ev_ebitda"]) if row["ev_ebitda"] is not None else None,
        ev_revenue=float(row["ev_revenue"]) if row["ev_revenue"] is not None else None,
        fetched_at=row["fetched_at"],
    )


def _extract_ratios(p: FundamentalPeriod) -> RatiosData:
    return RatiosData(
        pe_ratio=p.pe_ratio,
        pb_ratio=p.pb_ratio,
        ps_ratio=p.ps_ratio,
        ev_ebitda=p.ev_ebitda,
        ev_revenue=p.ev_revenue,
        gross_margin=p.gross_margin,
        operating_margin=p.operating_margin,
        net_margin=p.net_margin,
        roe=p.roe,
        roic=p.roic,
        debt_to_equity=p.debt_to_equity,
        revenue_growth_yoy=p.revenue_growth_yoy,
    )


def _row_to_analyst(row: asyncpg.Record) -> AnalystData:
    return AnalystData(
        target_price_low=float(row["target_price_low"])
        if row["target_price_low"] is not None
        else None,
        target_price_mean=float(row["target_price_mean"])
        if row["target_price_mean"] is not None
        else None,
        target_price_high=float(row["target_price_high"])
        if row["target_price_high"] is not None
        else None,
        recommendation=row["recommendation"],
        num_analysts=row["num_analysts"],
        earnings_est_next_q=float(row["earnings_est_next_q"])
        if row["earnings_est_next_q"] is not None
        else None,
        revenue_est_next_q=_cents_to_dollars(row["revenue_est_next_q"]),
        fetched_at=row["fetched_at"],
    )
