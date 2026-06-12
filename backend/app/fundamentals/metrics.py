"""
On-demand financial-metric engine.

Metrics are computed from a time-series of raw statements only when requested
(registry of name → callable). Money line items are integer cents; valuation
metrics need a live price (dollars) injected from the websocket cache. Unit rule:
divide cents by 100 before combining with the price.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents.data import safe_div as _safe_div_untyped
from app.fundamentals.models import BaseFinancials, EquityFinancials, PeriodType


def safe_div(num: int | float | None, den: int | float | None) -> float | None:
    """Typed wrapper around app.agents.data.safe_div (keeps strict mypy happy)."""
    result: float | None = _safe_div_untyped(num, den)
    return result


# ── Flow vs stock items (for TTM synthesis) ───────────────────────────────────
_FLOW = [
    "revenue",
    "cogs",
    "gross_profit",
    "operating_income",
    "net_income",
    "ebitda",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "dividends_paid",
    "eps_basic",
    "eps_diluted",
]
_STOCK = [
    "total_assets",
    "total_liabilities",
    "total_equity",
    "total_debt",
    "cash_and_equiv",
    "current_assets",
    "current_liabilities",
    "inventory",
    "shares_basic",
    "shares_diluted",
    "shares_outstanding",
]


def _dollars(cents: int | None) -> float | None:
    return None if cents is None else cents / 100.0


def to_ttm(quarterly: list[BaseFinancials]) -> EquityFinancials | None:
    """Synthesize a trailing-twelve-month statement from the last 4 quarters."""
    if len(quarterly) < 4:
        return None
    window = quarterly[:4]
    latest = window[0]
    fields: dict[str, Any] = {
        "symbol": latest.symbol,
        "asset_class": latest.asset_class,
        "period_type": "ttm",
        "period_end": latest.period_end,
        "fiscal_year": latest.fiscal_year,
        "currency": latest.currency,
        "source": latest.source,
    }
    for name in _FLOW:
        vals = [getattr(s, name) for s in window]
        fields[name] = sum(vals) if all(v is not None for v in vals) else None
    for name in _STOCK:
        fields[name] = getattr(latest, name, None)
    return EquityFinancials(**fields)


class MetricContext:
    def __init__(
        self,
        latest: BaseFinancials | None,
        series: list[BaseFinancials],
        period_type: PeriodType,
        live_price: float | None,
    ) -> None:
        self.latest = latest
        self.series = series  # most-recent-first, for growth/CAGR
        self.period_type = period_type
        self.live_price = live_price

    @property
    def yoy_offset(self) -> int:
        return 1 if self.period_type == "annual" else 4

    @property
    def shares(self) -> int | None:
        if self.latest is None:
            return None
        out = getattr(self.latest, "shares_outstanding", None)
        return out or getattr(self.latest, "shares_diluted", None)

    @property
    def market_cap(self) -> float | None:
        s = self.shares
        if self.live_price is None or s is None:
            return None
        return self.live_price * s


MetricFn = Callable[[MetricContext], float | None]
_METRICS: dict[str, MetricFn] = {}


def metric(name: str) -> Callable[[MetricFn], MetricFn]:
    def deco(fn: MetricFn) -> MetricFn:
        _METRICS[name] = fn
        return fn

    return deco


def available_metrics() -> list[str]:
    return sorted(_METRICS)


def _f(ctx: MetricContext, name: str) -> int | None:
    return getattr(ctx.latest, name, None) if ctx.latest is not None else None


# ── Margins ───────────────────────────────────────────────────────────────────
@metric("gross_margin")
def _gross_margin(c: MetricContext) -> float | None:
    return safe_div(_f(c, "gross_profit"), _f(c, "revenue"))


@metric("operating_margin")
def _operating_margin(c: MetricContext) -> float | None:
    return safe_div(_f(c, "operating_income"), _f(c, "revenue"))


@metric("net_margin")
def _net_margin(c: MetricContext) -> float | None:
    return safe_div(_f(c, "net_income"), _f(c, "revenue"))


# ── Returns ───────────────────────────────────────────────────────────────────
@metric("roe")
def _roe(c: MetricContext) -> float | None:
    return safe_div(_f(c, "net_income"), _f(c, "total_equity"))


@metric("roa")
def _roa(c: MetricContext) -> float | None:
    return safe_div(_f(c, "net_income"), _f(c, "total_assets"))


@metric("roic")
def _roic(c: MetricContext) -> float | None:
    eq, debt = _f(c, "total_equity"), _f(c, "total_debt")
    if eq is None and debt is None:
        return None
    return safe_div(_f(c, "net_income"), (eq or 0) + (debt or 0))


# ── Leverage / liquidity ──────────────────────────────────────────────────────
@metric("debt_to_equity")
def _debt_to_equity(c: MetricContext) -> float | None:
    return safe_div(_f(c, "total_debt"), _f(c, "total_equity"))


@metric("current_ratio")
def _current_ratio(c: MetricContext) -> float | None:
    return safe_div(_f(c, "current_assets"), _f(c, "current_liabilities"))


@metric("quick_ratio")
def _quick_ratio(c: MetricContext) -> float | None:
    ca, inv, cl = _f(c, "current_assets"), _f(c, "inventory"), _f(c, "current_liabilities")
    if ca is None or cl is None:
        return None
    return safe_div(ca - (inv or 0), cl)


# ── Growth ────────────────────────────────────────────────────────────────────
def _yoy(c: MetricContext, field: str) -> float | None:
    off = c.yoy_offset
    if len(c.series) <= off:
        return None
    cur = getattr(c.series[0], field, None)
    prior = getattr(c.series[off], field, None)
    if cur is None or prior is None:
        return None
    return safe_div(cur - prior, abs(prior) if prior else None)


@metric("revenue_growth_yoy")
def _rev_yoy(c: MetricContext) -> float | None:
    return _yoy(c, "revenue")


@metric("eps_growth_yoy")
def _eps_yoy(c: MetricContext) -> float | None:
    return _yoy(c, "eps_diluted")


def _cagr(c: MetricContext, field: str, years: int) -> float | None:
    periods = years * (1 if c.period_type == "annual" else 4)
    if len(c.series) <= periods:
        return None
    end = getattr(c.series[0], field, None)
    start = getattr(c.series[periods], field, None)
    if end is None or start is None or start <= 0 or end <= 0:
        return None
    end_v, start_v = float(end), float(start)
    return float(round((end_v / start_v) ** (1.0 / years) - 1.0, 6))


@metric("revenue_cagr_3y")
def _rev_cagr3(c: MetricContext) -> float | None:
    return _cagr(c, "revenue", 3)


@metric("revenue_cagr_5y")
def _rev_cagr5(c: MetricContext) -> float | None:
    return _cagr(c, "revenue", 5)


@metric("eps_cagr_3y")
def _eps_cagr3(c: MetricContext) -> float | None:
    return _cagr(c, "eps_diluted", 3)


# ── Valuation (need live price) ───────────────────────────────────────────────
@metric("pe")
def _pe(c: MetricContext) -> float | None:
    eps = _f(c, "eps_diluted")  # latest period (ttm if period=ttm)
    return safe_div(c.live_price, eps)


@metric("pb")
def _pb(c: MetricContext) -> float | None:
    bvps = safe_div(_dollars(_f(c, "total_equity")), c.shares)
    return safe_div(c.live_price, bvps)


@metric("ps")
def _ps(c: MetricContext) -> float | None:
    return safe_div(c.market_cap, _dollars(_f(c, "revenue")))


@metric("ev_ebitda")
def _ev_ebitda(c: MetricContext) -> float | None:
    mc = c.market_cap
    if mc is None:
        return None
    ev = mc + (_dollars(_f(c, "total_debt")) or 0.0) - (_dollars(_f(c, "cash_and_equiv")) or 0.0)
    return safe_div(ev, _dollars(_f(c, "ebitda")))


class FundamentalMetrics:
    """Computes requested metrics on demand from a statement series + live price."""

    def __init__(self, ctx: MetricContext) -> None:
        self.ctx = ctx

    def compute(self, requested: list[str]) -> tuple[dict[str, float | None], list[str]]:
        out: dict[str, float | None] = {}
        unknown: list[str] = []
        for name in requested:
            fn = _METRICS.get(name)
            if fn is None:
                unknown.append(name)
            else:
                out[name] = fn(self.ctx)
        return out, unknown
