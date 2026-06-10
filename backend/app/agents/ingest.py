"""
Fundamentals ingestor — upserts fetched data into the DB.
Fully idempotent: safe to run any number of times.
"""

from __future__ import annotations

import time
from typing import Any

import asyncpg
from app.agents.data import fetch_fundamentals


async def ingest_fundamentals(symbol: str, conn: asyncpg.Connection) -> dict[str, Any]:
    """
    Fetch and upsert all fundamentals for a ticker.
    Returns: { symbol, periods_written, analyst_updated, elapsed_ms }
    """
    start = time.monotonic()
    data = await fetch_fundamentals(symbol)

    equity_meta = data["equity"]
    periods_written = 0
    analyst_updated = False

    # ── 1. Upsert equity row ──────────────────────────────────────────────────
    equity_id: int = await conn.fetchval(
        """
        INSERT INTO equities (symbol, name, exchange, gics_sector, gics_industry, gics_sub_industry, market_cap_tier)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (symbol) DO UPDATE
            SET name              = EXCLUDED.name,
                exchange          = COALESCE(EXCLUDED.exchange, equities.exchange),
                gics_sector       = COALESCE(EXCLUDED.gics_sector, equities.gics_sector),
                gics_industry     = COALESCE(EXCLUDED.gics_industry, equities.gics_industry),
                market_cap_tier   = COALESCE(EXCLUDED.market_cap_tier, equities.market_cap_tier),
                is_active         = TRUE
        RETURNING id
        """,
        equity_meta["symbol"],
        equity_meta["name"],
        equity_meta["exchange"],
        equity_meta["gics_sector"],
        equity_meta["gics_industry"],
        equity_meta["gics_sub_industry"],
        equity_meta["market_cap_tier"],
    )

    # ── 2. Upsert fundamentals rows ───────────────────────────────────────────
    all_periods = data["annual"] + data["quarterly"]

    for p in all_periods:
        await conn.execute(
            """
            INSERT INTO fundamentals (
                equity_id, period_type, period_end, fiscal_year, fiscal_quarter, source,
                revenue, gross_profit, operating_income, net_income, ebitda,
                eps_basic, eps_diluted, shares_basic, shares_diluted,
                cash_and_equiv, total_assets, total_liabilities, total_equity, total_debt, net_debt,
                operating_cash_flow, capex, free_cash_flow, dividends_paid,
                gross_margin, operating_margin, net_margin, roe, roa, roic,
                debt_to_equity, current_ratio, quick_ratio, revenue_growth_yoy, eps_growth_yoy,
                price_at_fetch, market_cap, pe_ratio, pb_ratio, ps_ratio, ev_ebitda, ev_revenue,
                fetched_at
            ) VALUES (
                $1,$2,$3,$4,$5,'yfinance',
                $6,$7,$8,$9,$10,
                $11,$12,$13,$14,
                $15,$16,$17,$18,$19,$20,
                $21,$22,$23,$24,
                $25,$26,$27,$28,$29,$30,
                $31,$32,$33,$34,$35,
                $36,$37,$38,$39,$40,$41,$42,
                NOW()
            )
            ON CONFLICT (equity_id, period_type, period_end) DO UPDATE SET
                fiscal_year         = EXCLUDED.fiscal_year,
                fiscal_quarter      = EXCLUDED.fiscal_quarter,
                revenue             = COALESCE(EXCLUDED.revenue, fundamentals.revenue),
                gross_profit        = COALESCE(EXCLUDED.gross_profit, fundamentals.gross_profit),
                operating_income    = COALESCE(EXCLUDED.operating_income, fundamentals.operating_income),
                net_income          = COALESCE(EXCLUDED.net_income, fundamentals.net_income),
                ebitda              = COALESCE(EXCLUDED.ebitda, fundamentals.ebitda),
                eps_basic           = COALESCE(EXCLUDED.eps_basic, fundamentals.eps_basic),
                eps_diluted         = COALESCE(EXCLUDED.eps_diluted, fundamentals.eps_diluted),
                shares_basic        = COALESCE(EXCLUDED.shares_basic, fundamentals.shares_basic),
                shares_diluted      = COALESCE(EXCLUDED.shares_diluted, fundamentals.shares_diluted),
                cash_and_equiv      = COALESCE(EXCLUDED.cash_and_equiv, fundamentals.cash_and_equiv),
                total_assets        = COALESCE(EXCLUDED.total_assets, fundamentals.total_assets),
                total_liabilities   = COALESCE(EXCLUDED.total_liabilities, fundamentals.total_liabilities),
                total_equity        = COALESCE(EXCLUDED.total_equity, fundamentals.total_equity),
                total_debt          = COALESCE(EXCLUDED.total_debt, fundamentals.total_debt),
                net_debt            = COALESCE(EXCLUDED.net_debt, fundamentals.net_debt),
                operating_cash_flow = COALESCE(EXCLUDED.operating_cash_flow, fundamentals.operating_cash_flow),
                capex               = COALESCE(EXCLUDED.capex, fundamentals.capex),
                free_cash_flow      = COALESCE(EXCLUDED.free_cash_flow, fundamentals.free_cash_flow),
                dividends_paid      = COALESCE(EXCLUDED.dividends_paid, fundamentals.dividends_paid),
                gross_margin        = COALESCE(EXCLUDED.gross_margin, fundamentals.gross_margin),
                operating_margin    = COALESCE(EXCLUDED.operating_margin, fundamentals.operating_margin),
                net_margin          = COALESCE(EXCLUDED.net_margin, fundamentals.net_margin),
                roe                 = COALESCE(EXCLUDED.roe, fundamentals.roe),
                roa                 = COALESCE(EXCLUDED.roa, fundamentals.roa),
                roic                = COALESCE(EXCLUDED.roic, fundamentals.roic),
                debt_to_equity      = COALESCE(EXCLUDED.debt_to_equity, fundamentals.debt_to_equity),
                revenue_growth_yoy  = COALESCE(EXCLUDED.revenue_growth_yoy, fundamentals.revenue_growth_yoy),
                eps_growth_yoy      = COALESCE(EXCLUDED.eps_growth_yoy, fundamentals.eps_growth_yoy),
                price_at_fetch      = COALESCE(EXCLUDED.price_at_fetch, fundamentals.price_at_fetch),
                market_cap          = COALESCE(EXCLUDED.market_cap, fundamentals.market_cap),
                pe_ratio            = COALESCE(EXCLUDED.pe_ratio, fundamentals.pe_ratio),
                pb_ratio            = COALESCE(EXCLUDED.pb_ratio, fundamentals.pb_ratio),
                ps_ratio            = COALESCE(EXCLUDED.ps_ratio, fundamentals.ps_ratio),
                ev_ebitda           = COALESCE(EXCLUDED.ev_ebitda, fundamentals.ev_ebitda),
                ev_revenue          = COALESCE(EXCLUDED.ev_revenue, fundamentals.ev_revenue),
                fetched_at          = NOW()
            """,
            equity_id,
            p["period_type"],
            p["period_end"],
            p["fiscal_year"],
            p["fiscal_quarter"],
            p["revenue"],
            p["gross_profit"],
            p["operating_income"],
            p["net_income"],
            p["ebitda"],
            p["eps_basic"],
            p["eps_diluted"],
            p["shares_basic"],
            p["shares_diluted"],
            p["cash_and_equiv"],
            p["total_assets"],
            p["total_liabilities"],
            p["total_equity"],
            p["total_debt"],
            p["net_debt"],
            p["operating_cash_flow"],
            p["capex"],
            p["free_cash_flow"],
            p["dividends_paid"],
            p["gross_margin"],
            p["operating_margin"],
            p["net_margin"],
            p["roe"],
            p["roa"],
            p["roic"],
            p["debt_to_equity"],
            p["current_ratio"],
            p["quick_ratio"],
            p["revenue_growth_yoy"],
            p["eps_growth_yoy"],
            p["price_at_fetch"],
            p["market_cap"],
            p["pe_ratio"],
            p["pb_ratio"],
            p["ps_ratio"],
            p["ev_ebitda"],
            p["ev_revenue"],
        )
        periods_written += 1

    # ── 3. Insert analyst estimates (keep history) ────────────────────────────
    analyst = data.get("analyst")
    if analyst:
        await conn.execute(
            """
            INSERT INTO analyst_estimates (
                equity_id, fetched_at,
                target_price_low, target_price_mean, target_price_high,
                recommendation, num_analysts,
                earnings_est_next_q, revenue_est_next_q
            ) VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8)
            """,
            equity_id,
            analyst.get("target_price_low"),
            analyst.get("target_price_mean"),
            analyst.get("target_price_high"),
            analyst.get("recommendation"),
            analyst.get("num_analysts"),
            analyst.get("earnings_est_next_q"),
            analyst.get("revenue_est_next_q"),
        )
        analyst_updated = True

    elapsed_ms = int((time.monotonic() - start) * 1000)
    print(f"[ingest] {symbol}: {periods_written} periods written in {elapsed_ms}ms")

    return {
        "symbol": symbol.upper(),
        "periods_written": periods_written,
        "analyst_updated": analyst_updated,
        "elapsed_ms": elapsed_ms,
    }
