"""
Fundamentals data fetcher — yfinance → structured dict.

All monetary values returned as integer cents (×100) to avoid float precision loss.
Runs yfinance synchronously in a thread executor to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime
from typing import Any

import pandas as pd
import yfinance as yf

# ── Money helpers ──────────────────────────────────────────────────────────────


def to_cents(value: Any) -> int | None:
    """Convert a dollar float to integer cents. Returns None for missing/NaN."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return int(round(f * 100))


def to_float(value: Any) -> float | None:
    """Safe float conversion. Returns None for missing/NaN."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def safe_div(num: int | float | None, den: int | float | None) -> float | None:
    """Safe division. Returns None if either operand is None or denominator is zero."""
    if num is None or den is None or den == 0:
        return None
    try:
        result = float(num) / float(den)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return round(result, 6)


# ── Period helpers ─────────────────────────────────────────────────────────────


def _period_end_to_date(ts: Any) -> date | None:
    """Convert pandas Timestamp or similar to a Python date."""
    if ts is None:
        return None
    if isinstance(ts, (pd.Timestamp, datetime)):
        return ts.date()
    if isinstance(ts, date):
        return ts
    try:
        result = pd.Timestamp(ts).date()
        return result if isinstance(result, date) else None
    except Exception:
        return None


def _fiscal_quarter(d: date) -> int:
    """Derive fiscal quarter from period_end month (calendar quarters)."""
    return (d.month - 1) // 3 + 1


# ── DataFrame row extractor ────────────────────────────────────────────────────


def _get(df: pd.DataFrame, row_key: str, col: Any) -> Any:
    """Safe get from a yfinance DataFrame (rows=metrics, cols=dates)."""
    if df is None or df.empty:
        return None
    if row_key not in df.index:
        return None
    try:
        val = df.loc[row_key, col]
        return None if pd.isna(val) else val
    except (KeyError, TypeError):
        return None


# ── Core fetch ────────────────────────────────────────────────────────────────


def _fetch_sync(symbol: str) -> dict[str, Any]:
    """Synchronous fetch — runs in thread executor."""
    ticker = yf.Ticker(symbol)
    info = ticker.info or {}

    # Validate: yfinance returns a minimal dict for unknown symbols
    if not info.get("symbol") and not info.get("shortName") and not info.get("longName"):
        raise ValueError(f"No data found for symbol: {symbol}")

    fin_a = ticker.financials  # annual, cols = period_end dates
    fin_q = ticker.quarterly_financials
    bs_a = ticker.balance_sheet
    bs_q = ticker.quarterly_balance_sheet
    cf_a = ticker.cashflow
    cf_q = ticker.quarterly_cashflow

    # ── Build period rows ──────────────────────────────────────────────────────

    def _build_periods(
        fin: pd.DataFrame,
        bs: pd.DataFrame,
        cf: pd.DataFrame,
        period_type: str,
    ) -> list[dict[str, Any]]:
        if fin is None or fin.empty:
            return []

        rows = []
        # yfinance cols are Timestamps (most recent first)
        cols = list(fin.columns)

        for i, col in enumerate(cols):
            period_end = _period_end_to_date(col)
            if period_end is None:
                continue

            # Income statement
            revenue = to_cents(_get(fin, "Total Revenue", col))
            gross_profit = to_cents(_get(fin, "Gross Profit", col))
            operating_income = to_cents(_get(fin, "Operating Income", col))
            net_income = to_cents(_get(fin, "Net Income", col))
            ebitda = to_cents(_get(fin, "EBITDA", col))
            eps_basic = to_float(_get(fin, "Basic EPS", col))
            eps_diluted = to_float(_get(fin, "Diluted EPS", col))
            shares_basic = to_cents(
                _get(fin, "Basic Average Shares", col)
            )  # stored as cents? No — shares are units
            shares_diluted = to_cents(_get(fin, "Diluted Average Shares", col))

            # Shares are count (not money) — override with direct int conversion
            def to_int(v: Any) -> int | None:
                if v is None:
                    return None
                try:
                    f = float(v)
                    return None if math.isnan(f) else int(f)
                except (TypeError, ValueError):
                    return None

            shares_basic = to_int(_get(fin, "Basic Average Shares", col))
            shares_diluted = to_int(_get(fin, "Diluted Average Shares", col))

            # Balance sheet
            cash_and_equiv = to_cents(_get(bs, "Cash And Cash Equivalents", col))
            total_assets = to_cents(_get(bs, "Total Assets", col))
            total_liabilities = to_cents(_get(bs, "Total Liabilities Net Minority Interest", col))
            total_equity = to_cents(_get(bs, "Stockholders Equity", col))
            total_debt = to_cents(_get(bs, "Total Debt", col))
            net_debt = (
                to_cents(
                    (float(_get(bs, "Total Debt", col) or 0))
                    - (float(_get(bs, "Cash And Cash Equivalents", col) or 0))
                )
                if _get(bs, "Total Debt", col) is not None
                else None
            )

            # Cash flow
            operating_cash_flow = to_cents(_get(cf, "Operating Cash Flow", col))
            capex = to_cents(_get(cf, "Capital Expenditure", col))
            dividends_paid = to_cents(_get(cf, "Common Stock Dividend Paid", col))

            # FCF = OCF + capex (capex is negative)
            free_cash_flow = (
                operating_cash_flow + capex
                if operating_cash_flow is not None and capex is not None
                else None
            )

            # ── Ratios (computed from cents, result is a pure ratio) ──────────
            # Convert cents back to dollars for ratio division (cents cancel out)
            gross_margin = safe_div(gross_profit, revenue)
            operating_margin = safe_div(operating_income, revenue)
            net_margin = safe_div(net_income, revenue)
            roe = safe_div(net_income, total_equity)
            roa = safe_div(net_income, total_assets)
            roic = (
                safe_div(net_income, (total_equity or 0) + (total_debt or 0))
                if total_equity is not None or total_debt is not None
                else None
            )
            debt_to_equity = safe_div(total_debt, total_equity)

            # YoY growth: compare to period 4 positions earlier (same quarter, prior year)
            yoy_offset = 4
            revenue_growth_yoy = None
            eps_growth_yoy = None
            if i + yoy_offset < len(cols):
                col_prior = cols[i + yoy_offset]
                rev_prior = to_cents(_get(fin, "Total Revenue", col_prior))
                eps_prior = to_float(_get(fin, "Diluted EPS", col_prior))
                revenue_growth_yoy = safe_div(
                    (revenue - rev_prior)
                    if revenue is not None and rev_prior is not None
                    else None,
                    rev_prior,
                )
                eps_growth_yoy = safe_div(
                    (eps_diluted - eps_prior)
                    if eps_diluted is not None and eps_prior is not None
                    else None,
                    abs(eps_prior) if eps_prior else None,
                )

            rows.append(
                {
                    "period_type": period_type,
                    "period_end": period_end,
                    "fiscal_year": period_end.year,
                    "fiscal_quarter": _fiscal_quarter(period_end)
                    if period_type == "quarterly"
                    else None,
                    "revenue": revenue,
                    "gross_profit": gross_profit,
                    "operating_income": operating_income,
                    "net_income": net_income,
                    "ebitda": ebitda,
                    "eps_basic": eps_basic,
                    "eps_diluted": eps_diluted,
                    "shares_basic": shares_basic,
                    "shares_diluted": shares_diluted,
                    "cash_and_equiv": cash_and_equiv,
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "total_equity": total_equity,
                    "total_debt": total_debt,
                    "net_debt": net_debt,
                    "operating_cash_flow": operating_cash_flow,
                    "capex": capex,
                    "free_cash_flow": free_cash_flow,
                    "dividends_paid": dividends_paid,
                    "gross_margin": gross_margin,
                    "operating_margin": operating_margin,
                    "net_margin": net_margin,
                    "roe": roe,
                    "roa": roa,
                    "roic": roic,
                    "debt_to_equity": debt_to_equity,
                    "current_ratio": None,  # not readily available from cashflow stmt
                    "quick_ratio": None,
                    "revenue_growth_yoy": revenue_growth_yoy,
                    "eps_growth_yoy": eps_growth_yoy,
                    "price_at_fetch": to_float(
                        info.get("currentPrice") or info.get("regularMarketPrice")
                    ),
                    "market_cap": to_cents(info.get("marketCap")),
                    "pe_ratio": to_float(info.get("trailingPE")),
                    "pb_ratio": to_float(info.get("priceToBook")),
                    "ps_ratio": to_float(info.get("priceToSalesTrailing12Months")),
                    "ev_ebitda": to_float(info.get("enterpriseToEbitda")),
                    "ev_revenue": to_float(info.get("enterpriseToRevenue")),
                }
            )

        return rows

    annual = _build_periods(fin_a, bs_a, cf_a, "annual")
    quarterly = _build_periods(fin_q, bs_q, cf_q, "quarterly")

    # ── Analyst data ──────────────────────────────────────────────────────────
    analyst: dict[str, Any] = {}
    try:
        targets = ticker.analyst_price_targets
        if targets and isinstance(targets, dict):
            analyst["target_price_low"] = to_float(targets.get("low"))
            analyst["target_price_mean"] = to_float(targets.get("mean"))
            analyst["target_price_high"] = to_float(targets.get("high"))
            analyst["num_analysts"] = int(targets.get("numberOfAnalysts") or 0) or None
    except Exception:
        pass

    try:
        recs = ticker.recommendations_summary
        if recs is not None and not recs.empty:
            # Most recent row
            row = recs.iloc[0]
            # Determine majority recommendation
            counts = {
                "strongBuy": int(row.get("strongBuy", 0) or 0),
                "buy": int(row.get("buy", 0) or 0),
                "hold": int(row.get("hold", 0) or 0),
                "sell": int(row.get("sell", 0) or 0),
                "strongSell": int(row.get("strongSell", 0) or 0),
            }
            analyst["recommendation"] = max(counts, key=lambda k: counts[k])
            analyst["earnings_est_next_q"] = to_float(info.get("forwardEps"))
            analyst["revenue_est_next_q"] = to_cents(
                info.get("revenueEstimates", {}).get("avg")
                if info.get("revenueEstimates")
                else None
            )
    except Exception:
        pass

    # ── Equity metadata ───────────────────────────────────────────────────────
    equity_meta = {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName") or symbol.upper(),
        "exchange": info.get("exchange") or info.get("fullExchangeName"),
        "gics_sector": info.get("sector"),
        "gics_industry": info.get("industry"),
        "gics_sub_industry": None,
        "market_cap": to_cents(info.get("marketCap")),
        "market_cap_tier": _market_cap_tier(to_cents(info.get("marketCap"))),
    }

    return {
        "equity": equity_meta,
        "annual": annual[:4],  # last 4 annual periods
        "quarterly": quarterly[:8],  # last 8 quarterly periods
        "analyst": analyst or None,
    }


def _market_cap_tier(market_cap_cents: int | None) -> str | None:
    if market_cap_cents is None:
        return None
    mc = market_cap_cents  # in cents (dollars × 100)
    if mc >= 200_000_000_000 * 100:  # $200B
        return "mega"
    if mc >= 10_000_000_000 * 100:  # $10B
        return "large"
    if mc >= 2_000_000_000 * 100:  # $2B
        return "mid"
    if mc >= 300_000_000 * 100:  # $300M
        return "small"
    return "micro"


# ── Public async interface ────────────────────────────────────────────────────


async def fetch_fundamentals(symbol: str) -> dict[str, Any]:
    """Async wrapper — runs yfinance in thread pool to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_sync, symbol)
