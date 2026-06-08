from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class EquityMeta(BaseModel):
    symbol: str
    name: str
    exchange: str | None
    sector: str | None
    industry: str | None
    market_cap_tier: str | None
    is_tracked: bool


class FundamentalPeriod(BaseModel):
    period_type: str
    period_end: date
    fiscal_year: int | None
    fiscal_quarter: int | None
    # Income statement (integer cents)
    revenue: int | None
    gross_profit: int | None
    operating_income: int | None
    net_income: int | None
    ebitda: int | None
    eps_basic: float | None
    eps_diluted: float | None
    shares_basic: int | None
    shares_diluted: int | None
    # Balance sheet
    cash_and_equiv: int | None
    total_assets: int | None
    total_liabilities: int | None
    total_equity: int | None
    total_debt: int | None
    net_debt: int | None
    # Cash flow
    operating_cash_flow: int | None
    capex: int | None
    free_cash_flow: int | None
    dividends_paid: int | None
    # Ratios
    gross_margin: float | None
    operating_margin: float | None
    net_margin: float | None
    roe: float | None
    roa: float | None
    roic: float | None
    debt_to_equity: float | None
    revenue_growth_yoy: float | None
    eps_growth_yoy: float | None
    # Valuation snapshot
    price_at_fetch: float | None
    market_cap: int | None
    pe_ratio: float | None
    pb_ratio: float | None
    ps_ratio: float | None
    ev_ebitda: float | None
    ev_revenue: float | None
    fetched_at: datetime | None


class RatiosData(BaseModel):
    pe_ratio: float | None
    pb_ratio: float | None
    ps_ratio: float | None
    ev_ebitda: float | None
    ev_revenue: float | None
    gross_margin: float | None
    operating_margin: float | None
    net_margin: float | None
    roe: float | None
    roic: float | None
    debt_to_equity: float | None
    revenue_growth_yoy: float | None


class AnalystData(BaseModel):
    target_price_low: float | None
    target_price_mean: float | None
    target_price_high: float | None
    recommendation: str | None
    num_analysts: int | None
    earnings_est_next_q: float | None
    revenue_est_next_q: int | None
    fetched_at: datetime | None


class FundamentalsResponse(BaseModel):
    equity: EquityMeta
    annual: list[FundamentalPeriod]
    quarterly: list[FundamentalPeriod]
    ratios: RatiosData
    analyst: AnalystData | None
    fetched_at: datetime | None


class IngestResult(BaseModel):
    symbol: str
    status: str  # 'ok' | 'error'
    periods_written: int | None = None
    analyst_updated: bool | None = None
    elapsed_ms: int | None = None
    error: str | None = None


class BatchIngestRequest(BaseModel):
    symbols: list[str]


class BatchIngestResponse(BaseModel):
    results: list[IngestResult]


class SearchResult(BaseModel):
    symbol: str
    name: str
    sector: str | None
    market_cap_tier: str | None
    is_tracked: bool
