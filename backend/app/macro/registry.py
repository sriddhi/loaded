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

# What each alert means and what it has historically implied. Educational
# context only — heuristics from the SVM playbook, not financial advice.
ALERT_INFO: dict[str, dict[str, str]] = {
    "policy_mistake": {
        "meaning": "Inflation momentum is fading while the Fed keeps policy tight "
        "instead of easing into the slowdown.",
        "impact": "Historically raises the odds of over-tightening into a downturn: "
        "growth and earnings can weaken, short yields tend to fall first, and rate-cut "
        "bets get pulled forward.",
    },
    "real_wages_negative": {
        "meaning": "Prices are rising faster than weekly wage income, so the average "
        "paycheck buys less each month.",
        "impact": "Squeezes discretionary spending with a lag — often shows up later in "
        "retail sales, consumer-facing earnings, and rising credit-card balances.",
    },
    "income_spread_falling_3m": {
        "meaning": "The cushion between income growth and inflation has narrowed three "
        "months in a row — the consumer trend is deteriorating, not just dipping.",
        "impact": "Persistent erosion tends to precede softer consumption; cyclical and "
        "low-end retail typically feel it first while staples hold up better.",
    },
    "cpi_up_2y_down": {
        "meaning": "Reported inflation ticked up but 2-year yields fell — the bond "
        "market is looking through the print toward weaker growth or future cuts.",
        "impact": "When bonds and CPI disagree, bonds have often been the better lead. "
        "Can foreshadow a growth scare: duration bid, cyclicals lagging defensives.",
    },
    "two_year_below_3_5": {
        "meaning": "The 2-year yield sits below 3.5%, i.e. markets are pricing a "
        "meaningfully lower Fed path than the current policy rate.",
        "impact": "Signals expected easing: historically supportive for bonds and "
        "longer-duration assets, and often coincides with late-cycle conditions.",
    },
    "ppi_hot_core_rolling": {
        "meaning": "Headline producer prices run >1.5pts above core while core fades — "
        "input-cost pressure is concentrated in food/energy, not broad demand.",
        "impact": "Headline inflation prints can stay noisy while underlying pricing "
        "power weakens — margin pressure builds for producers who can't pass costs on.",
    },
    "margin_squeeze": {
        "meaning": "Producer input costs (PPI) are rising faster than consumer prices "
        "(CPI) — companies are absorbing cost increases they can't pass through.",
        "impact": "Compresses gross margins with a lag; earnings-revision risk for "
        "goods producers, while pricing-power businesses tend to weather it better.",
    },
    "claims_4wk_above_250k": {
        "meaning": "The smoothed pace of new layoffs has crossed the ~250k line that "
        "historically separates a tight labor market from a softening one.",
        "impact": "Labor weakness is the classic late-cycle confirmation: consumption "
        "usually slows next, and the Fed's reaction function shifts toward cuts.",
    },
    "claims_spike_15pct": {
        "meaning": "This week's new claims jumped >15% above their 4-week average — an "
        "abrupt break rather than a drift.",
        "impact": "One week can be noise (strikes, weather, seasonality), but spikes "
        "that stick have marked the start of layoff cycles; watch the next 2–3 prints.",
    },
    "continuing_claims_rising_4w": {
        "meaning": "People already on unemployment are staying on it — four straight "
        "weekly increases means hiring is slowing beneath the surface.",
        "impact": "Longer unemployment spells drain savings and spending power; "
        "historically a steadier recession lead than the headline jobs number.",
    },
    "continuing_claims_12m_high": {
        "meaning": "Continuing claims just set a 12-month high — labor-market slack is "
        "at its widest point of the past year.",
        "impact": "New cycle highs in continuing claims have typically appeared in the "
        "months before broad slowdowns; consistent with building disinflation.",
    },
    "ecb_hike_market_rejects": {
        "meaning": "The ECB raised rates but German 10-year yields fell — the bond "
        "market is betting the hike won't stick or growth will crack first.",
        "impact": "Markets overruling a central bank often precedes policy reversals; "
        "watch EUR/USD and European bank margins for confirmation.",
    },
    "spy_21dma": {
        "meaning": "The S&P 500 ETF closed below its 21-day moving average — "
        "short-term trend momentum has flipped negative.",
        "impact": "A common de-risking trigger in trend-following playbooks; on its own "
        "it is noisy, but it gates many systematic buy signals until reclaimed.",
    },
    "igv_50dma": {
        "meaning": "Software (IGV) is holding above its 50-day moving average — "
        "intermediate trend in growth/software remains constructive.",
        "impact": "Strength in software vs the index suggests risk appetite for "
        "duration-sensitive growth is intact despite macro stress.",
    },
    "smh_50dma": {
        "meaning": "Semiconductors (SMH) are above their 50-day moving average — the "
        "market's classic cyclical-growth bellwether is still in an uptrend.",
        "impact": "Semis leading is historically consistent with risk-on conditions; a "
        "loss of the 50-day there has often front-run broader index weakness.",
    },
}
