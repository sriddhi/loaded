"""Upsert raw financial statements into the `financial_statements` table."""

from __future__ import annotations

import time
from typing import Any

import asyncpg
from app.fundamentals.data import fetch_raw_statements

# Raw line-item columns (order used by the INSERT). Period metadata handled separately.
_LINE_ITEMS = [
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


async def _upsert_equity(conn: asyncpg.Connection, equity: dict[str, Any]) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO equities (symbol, name, exchange, gics_sector, gics_industry,
                              asset_class, currency)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (symbol) DO UPDATE SET
            name = EXCLUDED.name,
            exchange = COALESCE(EXCLUDED.exchange, equities.exchange),
            gics_sector = COALESCE(EXCLUDED.gics_sector, equities.gics_sector),
            gics_industry = COALESCE(EXCLUDED.gics_industry, equities.gics_industry)
        RETURNING id
        """,
        equity["symbol"],
        equity["name"],
        equity.get("exchange"),
        equity.get("gics_sector"),
        equity.get("gics_industry"),
        equity.get("asset_class", "us_equity"),
        equity.get("currency", "USD"),
    )
    assert row is not None
    return int(row["id"])


async def ingest_statements(symbol: str, conn: asyncpg.Connection) -> dict[str, Any]:
    """Fetch raw statements from yfinance and upsert them. Idempotent."""
    started = time.monotonic()
    data = await fetch_raw_statements(symbol)
    equity_id = await _upsert_equity(conn, data["equity"])
    asset_class = data["equity"].get("asset_class", "us_equity")
    currency = data["equity"].get("currency", "USD")

    meta_cols = [
        "equity_id",
        "asset_class",
        "period_type",
        "period_end",
        "fiscal_year",
        "fiscal_quarter",
        "currency",
        "source",
    ]
    all_cols = meta_cols + _LINE_ITEMS
    placeholders = ", ".join(f"${i + 1}" for i in range(len(all_cols)))
    updates = ", ".join(
        f"{c} = COALESCE(EXCLUDED.{c}, financial_statements.{c})" for c in _LINE_ITEMS
    )
    sql = (
        f"INSERT INTO financial_statements ({', '.join(all_cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (equity_id, period_type, period_end) DO UPDATE SET "
        f"{updates}, fetched_at = NOW()"
    )

    written = 0
    for period in data["annual"] + data["quarterly"]:
        values: list[Any] = [
            equity_id,
            asset_class,
            period["period_type"],
            period["period_end"],
            period.get("fiscal_year"),
            period.get("fiscal_quarter"),
            currency,
            "yfinance",
        ]
        values.extend(period.get(c) for c in _LINE_ITEMS)
        await conn.execute(sql, *values)
        written += 1

    return {
        "symbol": symbol.upper(),
        "periods_written": written,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
