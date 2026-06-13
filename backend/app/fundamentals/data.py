"""
Raw financial-statement fetcher — yfinance → list of per-period dicts.

Unlike `app.agents.data` (which also computes + returns ratios), this returns ONLY
raw line items in integer cents. Metrics are computed on demand in `metrics.py`.
yfinance is synchronous, so it runs in a thread executor.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pandas as pd
import yfinance as yf
from app.agents.data import _fiscal_quarter, _get, _period_end_to_date, to_cents, to_float


def _to_int(value: Any) -> int | None:
    """Count conversion (shares) — not money, so no ×100."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else int(f)


def _fetch_raw_sync(symbol: str) -> dict[str, Any]:
    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    if not info.get("symbol") and not info.get("shortName") and not info.get("longName"):
        raise ValueError(f"No data found for symbol: {symbol}")

    shares_outstanding = _to_int(info.get("sharesOutstanding"))

    def _build(
        fin: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame, period_type: str
    ) -> list[dict[str, Any]]:
        if fin is None or fin.empty:
            return []
        rows: list[dict[str, Any]] = []
        for col in list(fin.columns):
            period_end = _period_end_to_date(col)
            if period_end is None:
                continue
            operating_cash_flow = to_cents(_get(cf, "Operating Cash Flow", col))
            capex = to_cents(_get(cf, "Capital Expenditure", col))
            free_cash_flow = (
                operating_cash_flow + capex
                if operating_cash_flow is not None and capex is not None
                else None
            )
            rows.append(
                {
                    "period_type": period_type,
                    "period_end": period_end,
                    "fiscal_year": period_end.year,
                    "fiscal_quarter": _fiscal_quarter(period_end)
                    if period_type == "quarterly"
                    else None,
                    # Income statement
                    "revenue": to_cents(_get(fin, "Total Revenue", col)),
                    "cogs": to_cents(_get(fin, "Cost Of Revenue", col)),
                    "gross_profit": to_cents(_get(fin, "Gross Profit", col)),
                    "operating_income": to_cents(_get(fin, "Operating Income", col)),
                    "net_income": to_cents(_get(fin, "Net Income", col)),
                    "ebitda": to_cents(_get(fin, "EBITDA", col)),
                    "eps_basic": to_float(_get(fin, "Basic EPS", col)),
                    "eps_diluted": to_float(_get(fin, "Diluted EPS", col)),
                    "shares_basic": _to_int(_get(fin, "Basic Average Shares", col)),
                    "shares_diluted": _to_int(_get(fin, "Diluted Average Shares", col)),
                    "shares_outstanding": shares_outstanding,
                    # Balance sheet
                    "total_assets": to_cents(_get(bs, "Total Assets", col)),
                    "total_liabilities": to_cents(
                        _get(bs, "Total Liabilities Net Minority Interest", col)
                    ),
                    "total_equity": to_cents(_get(bs, "Stockholders Equity", col)),
                    "total_debt": to_cents(_get(bs, "Total Debt", col)),
                    "cash_and_equiv": to_cents(_get(bs, "Cash And Cash Equivalents", col)),
                    "current_assets": to_cents(_get(bs, "Current Assets", col)),
                    "current_liabilities": to_cents(_get(bs, "Current Liabilities", col)),
                    "inventory": to_cents(_get(bs, "Inventory", col)),
                    # Cash flow
                    "operating_cash_flow": operating_cash_flow,
                    "capex": capex,
                    "free_cash_flow": free_cash_flow,
                    "dividends_paid": to_cents(_get(cf, "Common Stock Dividend Paid", col)),
                }
            )
        return rows

    annual = _build(ticker.financials, ticker.balance_sheet, ticker.cashflow, "annual")
    quarterly = _build(
        ticker.quarterly_financials,
        ticker.quarterly_balance_sheet,
        ticker.quarterly_cashflow,
        "quarterly",
    )

    equity = {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName") or symbol.upper(),
        "exchange": info.get("exchange") or info.get("fullExchangeName"),
        "gics_sector": info.get("sector"),
        "gics_industry": info.get("industry"),
        "asset_class": "us_equity",
        "currency": info.get("currency") or "USD",
    }
    return {"equity": equity, "annual": annual[:4], "quarterly": quarterly[:8]}


async def fetch_raw_statements(symbol: str) -> dict[str, Any]:
    """Async wrapper — runs yfinance in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_raw_sync, symbol)
