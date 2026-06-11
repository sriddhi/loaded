"""
OOP financial-data models for the fundamentals module.

A generic `BaseFinancials` holds line items common to any asset; concrete asset
types subclass it and register themselves. New asset classes (ETF, crypto, bank…)
plug in via `register_financials` + a subclass — no edits to a central union.

Money line items are integer **cents** (matching the platform convention);
ratios/prices are floats. Cheap per-row derivations use `@computed_field`; heavier
cross-period metrics live in `metrics.py` so they aren't recomputed on every
serialization.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, computed_field

PeriodType = Literal["annual", "quarterly", "ttm"]


class BaseFinancials(BaseModel):
    """Common financial-statement line items for any asset class."""

    model_config = ConfigDict(frozen=True)

    # Registry key — subclasses override.
    asset_class_key: ClassVar[str] = "base"

    # ── Period metadata ──────────────────────────────────────────────────────
    symbol: str
    asset_class: str = "us_equity"
    period_type: PeriodType
    period_end: date
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    currency: str = "USD"
    source: str = "yfinance"

    # ── Income statement (integer cents) ─────────────────────────────────────
    revenue: int | None = None
    cogs: int | None = None
    gross_profit: int | None = None
    operating_income: int | None = None
    net_income: int | None = None
    ebitda: int | None = None

    # ── Balance sheet (integer cents) ────────────────────────────────────────
    total_assets: int | None = None
    total_liabilities: int | None = None
    total_equity: int | None = None
    total_debt: int | None = None
    cash_and_equiv: int | None = None
    current_assets: int | None = None
    current_liabilities: int | None = None
    inventory: int | None = None

    # ── Cash flow (integer cents) ────────────────────────────────────────────
    operating_cash_flow: int | None = None
    capex: int | None = None  # negative (outflow)
    free_cash_flow: int | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gross_margin(self) -> float | None:
        """Cheap per-row derivation (cents cancel)."""
        from app.agents.data import safe_div

        result: float | None = safe_div(self.gross_profit, self.revenue)
        return result


class EquityFinancials(BaseFinancials):
    """US-equity financials — adds per-share and ownership line items."""

    asset_class_key: ClassVar[str] = "us_equity"

    eps_basic: float | None = None
    eps_diluted: float | None = None
    shares_basic: int | None = None
    shares_diluted: int | None = None
    shares_outstanding: int | None = None
    dividends_paid: int | None = None  # cents, negative


# ── Registry + factory ────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[BaseFinancials]] = {}


def register_financials(cls: type[BaseFinancials]) -> type[BaseFinancials]:
    """Register a financials subclass under its `asset_class_key`."""
    _REGISTRY[cls.asset_class_key] = cls
    return cls


def build_financials(asset_class: str, **fields: Any) -> BaseFinancials:
    """Construct the right financials model for an asset class (default: equity)."""
    cls = _REGISTRY.get(asset_class, EquityFinancials)
    return cls(asset_class=asset_class, **fields)


register_financials(EquityFinancials)


# ── API request/response models ───────────────────────────────────────────────


class RefreshResult(BaseModel):
    symbol: str
    periods_written: int
    elapsed_ms: int


class StatementsResponse(BaseModel):
    symbol: str
    period_type: PeriodType
    statements: list[EquityFinancials]
    as_of: datetime | None = None  # latest fetched_at — surfaces freshness


class MetricsResponse(BaseModel):
    symbol: str
    period: PeriodType
    metrics: dict[str, float | None]
    price_used: float | None
    unknown_metrics: list[str] = []
    as_of: datetime | None = None


class PriceResponse(BaseModel):
    symbol: str
    price: float
    ts: datetime
    stale: bool
    source: str = "finnhub"


class ForwardResponse(BaseModel):
    symbol: str
    price: float | None = None
    forward_eps: float | None = None
    trailing_eps: float | None = None
    forward_pe: float | None = None  # price / forward_eps; None when not determinable


class HorizonOutlook(BaseModel):
    horizon: str  # 1d | 1w | 1mo | 1y | 3y | 5y
    label: str  # buy | sell | neutral
    confidence: int  # 0-100


class OutlookResponse(BaseModel):
    symbol: str
    price: float | None = None
    fair_value: dict[str, Any] | None = None
    upside_pct: float | None = None  # to fair value
    horizons: list[HorizonOutlook] = []
    tags: list[str] = []
    disclaimer: str = "Heuristic estimate — not a prediction or financial advice."


class TrackedEquity(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    market_cap_tier: str | None = None
