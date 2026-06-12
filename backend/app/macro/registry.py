"""Series + tracker registry for the macro module (SVM chart playbook)."""

from __future__ import annotations

from typing import Any

# frequency → refresh TTL hours ("stay up to date as FRED updates")
TTL_HOURS = {"d": 6, "w": 12, "m": 24}

# code → (title, frequency d|w|m, category)
SERIES: dict[str, dict[str, str]] = {
    "CPIAUCSL": {"title": "CPI, All Urban Consumers", "freq": "m", "category": "inflation"},
    "DFF": {"title": "Federal Funds Effective Rate (daily)", "freq": "d", "category": "rates"},
    "FEDFUNDS": {"title": "Federal Funds Rate (monthly)", "freq": "m", "category": "rates"},
    "AWHNONAG": {"title": "Avg Weekly Hours, Prod & Nonsup", "freq": "m", "category": "labor"},
    "AHETPI": {"title": "Avg Hourly Earnings, Prod & Nonsup", "freq": "m", "category": "labor"},
    "DGS2": {"title": "2-Year Treasury Yield", "freq": "d", "category": "rates"},
    "DGS10": {"title": "10-Year Treasury Yield", "freq": "d", "category": "rates"},
    "PPIFIS": {"title": "PPI Final Demand (headline)", "freq": "m", "category": "inflation"},
    "WPSFD4131": {
        "title": "PPI Final Demand ex Food & Energy",
        "freq": "m",
        "category": "inflation",
    },
    "ICSA": {"title": "Initial Jobless Claims (SA)", "freq": "w", "category": "labor"},
    "CCSA": {"title": "Continuing Claims (SA)", "freq": "w", "category": "labor"},
    "PAYEMS": {"title": "Nonfarm Payrolls", "freq": "m", "category": "labor"},
    "ECBDFR": {"title": "ECB Deposit Facility Rate", "freq": "d", "category": "europe"},
    "IRLTLT01DEM156N": {"title": "Germany 10Y Yield (monthly)", "freq": "m", "category": "europe"},
    "DEXUSEU": {"title": "EUR/USD", "freq": "d", "category": "europe"},
}

# The 8 FRED chart trackers from the video, each with its series + linked alerts.
TRACKERS: list[dict[str, Any]] = [
    {
        "id": "cpi_vs_fedfunds",
        "title": "CPI (YoY) vs Federal Funds Rate",
        "series": ["CPIAUCSL", "DFF"],
        "derived": ["CPIAUCSL_yoy"],
        "alerts": ["policy_mistake"],
        "note": "The 'hike into rolling-over inflation, then capitulate' pattern.",
    },
    {
        "id": "cpi_vs_wage_income",
        "title": "CPI vs Wage Income of Prod & Nonsup Workers (YoY)",
        "series": ["CPIAUCSL", "AWHNONAG", "AHETPI"],
        "derived": ["CPIAUCSL_yoy", "income_yoy"],
        "alerts": ["real_wages_negative", "income_spread_falling_3m"],
        "note": "Weekly income = hours × earnings. Inflation above it crushes demand.",
    },
    {
        "id": "cpi_vs_2y",
        "title": "CPI (YoY) vs 2-Year Treasury Yield",
        "series": ["CPIAUCSL", "DGS2"],
        "derived": ["CPIAUCSL_yoy"],
        "alerts": ["cpi_up_2y_down", "two_year_below_3_5"],
        "note": "If the bond market believed inflation, the 2Y would follow CPI up.",
    },
    {
        "id": "ppi_headline_vs_core",
        "title": "PPI Final Demand vs Core PPI (YoY)",
        "series": ["PPIFIS", "WPSFD4131"],
        "derived": ["PPIFIS_yoy", "WPSFD4131_yoy"],
        "alerts": ["ppi_hot_core_rolling"],
        "note": "Headline outrunning core = energy/food pulse, likely short-lived.",
    },
    {
        "id": "cpi_ppi_spread",
        "title": "CPI−PPI Spread (corporate margin proxy)",
        "series": ["CPIAUCSL", "PPIFIS"],
        "derived": ["cpi_ppi_spread"],
        "alerts": ["margin_squeeze"],
        "note": "Negative = producer prices outrunning consumer prices = layoffs ahead.",
    },
    {
        "id": "initial_claims",
        "title": "Initial Jobless Claims",
        "series": ["ICSA"],
        "derived": ["icsa_4wk"],
        "alerts": ["claims_4wk_above_250k", "claims_spike_15pct"],
        "note": "First crack in the labor market as margins compress.",
    },
    {
        "id": "continuing_claims",
        "title": "Continuing Claims",
        "series": ["CCSA", "PAYEMS"],
        "derived": [],
        "alerts": ["continuing_claims_rising_4w", "continuing_claims_12m_high"],
        "note": "People staying unemployed longer — spending power draining.",
    },
    {
        "id": "ecb_and_bunds",
        "title": "ECB Deposit Rate vs German 10Y & EUR/USD",
        "series": ["ECBDFR", "IRLTLT01DEM156N", "DEXUSEU"],
        "derived": [],
        "alerts": ["ecb_hike_market_rejects"],
        "note": "Rate hike met by falling yields = the market overruling the central bank.",
    },
]

# Technical trackers (pattern 4) — priced via the existing close fetcher.
TECHNICALS: list[dict[str, Any]] = [
    {"id": "spy_21dma", "symbol": "SPY", "ma": 21, "direction": "below"},
    {"id": "igv_50dma", "symbol": "IGV", "ma": 50, "direction": "above"},
    {"id": "smh_50dma", "symbol": "SMH", "ma": 50, "direction": "above"},
]
