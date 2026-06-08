# Generator: Fundamentals Data Pipeline

**Module:** `backend/app/agents/`
**Linear:** DHA-22, DHA-23
**Lock before building.**

---

## What to Build

A fundamentals data pipeline that fetches financial data from yfinance for any US equity ticker, computes derived ratios, and stores everything in the `fundamentals` and `analyst_estimates` tables with full idempotency.

---

## Files to Create

```
backend/app/agents/__init__.py        — empty
backend/app/agents/models.py          — Pydantic response models
backend/app/agents/data.py            — yfinance fetch + ratio computation
backend/app/agents/ingest.py          — DB upsert logic
backend/app/agents/router.py          — FastAPI router
backend/tests/test_agents_fundamentals.py
```

---

## 1. `data.py` — Fetch + Compute

### Function signature
```python
async def fetch_fundamentals(symbol: str) -> dict:
    """
    Fetch all fundamental data for a ticker from yfinance.
    Returns a dict with keys: info, annual, quarterly, analyst.
    Raises ValueError if ticker is not found / no data returned.
    """
```

### Data sources (all via `yfinance.Ticker(symbol)`)

| Attribute | Content | Use |
|---|---|---|
| `.info` | Price, market cap, sector, P/E, P/B, P/S, EV/EBITDA, shares outstanding | Valuation snapshot + equity metadata |
| `.financials` | Annual income statement, last 4 fiscal years | Revenue, gross profit, operating income, net income, EBITDA, EPS |
| `.quarterly_financials` | Quarterly income statement, last 8 quarters | Same fields quarterly |
| `.balance_sheet` | Annual balance sheet | Cash, assets, liabilities, equity, debt |
| `.quarterly_balance_sheet` | Quarterly balance sheet | Same fields quarterly |
| `.cashflow` | Annual cash flow | Operating CF, CapEx, dividends |
| `.quarterly_cashflow` | Quarterly cash flow | Same fields quarterly |
| `.analyst_price_targets` | Analyst price targets dict | low, mean, high, num_analysts |
| `.recommendations_summary` | DataFrame of recommendation counts | strongBuy, buy, hold, sell, strongSell |

### Money storage rule — NON-NEGOTIABLE
All monetary values (revenue, assets, cash, etc.) are stored as **integer cents** (multiply by 100, round to nearest integer, cast to int). This prevents float precision drift across billions of dollars.

```python
def to_cents(value: float | None) -> int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return int(round(float(value) * 100))
```

EPS and ratio values stay as `float` (NUMERIC columns) — only absolute dollar amounts use cents.

### Derived ratios to compute (from raw data, not from `.info`)

```python
# All computed from the integer-cents values BEFORE storage
gross_margin       = gross_profit / revenue  (if revenue != 0)
operating_margin   = operating_income / revenue
net_margin         = net_income / revenue
roe                = net_income / total_equity
roa                = net_income / total_assets
roic               = net_income / (total_equity + total_debt)  # simplified ROIC
debt_to_equity     = total_debt / total_equity
free_cash_flow     = operating_cash_flow + capex  # capex is negative in yfinance
revenue_growth_yoy = (rev_t - rev_t_minus_4) / abs(rev_t_minus_4)  # t vs 4 quarters ago
eps_growth_yoy     = (eps_t - eps_t_minus_4) / abs(eps_t_minus_4)
```

All ratios: return `None` if denominator is zero or inputs are missing. Store as `NUMERIC(8,4)`.

### Period type detection
- Annual: `period_type = 'annual'`, `fiscal_quarter = None`
- Quarterly: `period_type = 'quarterly'`, `fiscal_quarter` = 1–4 derived from `period_end` month:
  - Jan/Feb/Mar → Q1, Apr/May/Jun → Q2, Jul/Aug/Sep → Q3, Oct/Nov/Dec → Q4
- `fiscal_year` = year of `period_end`

### yfinance field name mapping

yfinance uses inconsistent capitalization. Always use `.get()` with None default:

```python
# Income statement keys (from .financials columns)
"Total Revenue" → revenue
"Gross Profit" → gross_profit
"Operating Income" → operating_income
"Net Income" → net_income
"EBITDA" → ebitda
"Basic EPS" → eps_basic
"Diluted EPS" → eps_diluted
"Basic Average Shares" → shares_basic
"Diluted Average Shares" → shares_diluted

# Balance sheet keys
"Cash And Cash Equivalents" → cash_and_equiv
"Total Assets" → total_assets
"Total Liabilities Net Minority Interest" → total_liabilities
"Stockholders Equity" → total_equity
"Total Debt" → total_debt

# Cash flow keys
"Operating Cash Flow" → operating_cash_flow
"Capital Expenditure" → capex  (negative value)
"Common Stock Dividend Paid" → dividends_paid  (negative value)
```

---

## 2. `ingest.py` — DB Upsert

### Function signature
```python
async def ingest_fundamentals(symbol: str, conn: asyncpg.Connection) -> dict:
    """
    Fetch fundamentals for symbol and upsert into DB.
    Returns { symbol, periods_written, analyst_updated, elapsed_ms }.
    Fully idempotent — safe to run multiple times.
    """
```

### Upsert logic

**Equity row:** `ON CONFLICT (symbol) DO UPDATE SET name, gics_sector, gics_industry, market_cap_tier, is_active = TRUE`

**Fundamentals rows:** For each annual + quarterly period:
```sql
INSERT INTO fundamentals (...all columns...)
VALUES (...)
ON CONFLICT (equity_id, period_type, period_end)
DO UPDATE SET
    revenue = EXCLUDED.revenue,
    -- all other columns...
    fetched_at = NOW()
```

**Analyst estimates:** Always insert a fresh row (do not upsert — keep history):
```sql
INSERT INTO analyst_estimates (equity_id, fetched_at, target_price_low, ...)
VALUES (...)
```

### market_cap_tier derivation from market_cap (in cents):
```
>= 200_000_000_000_00  → 'mega'    (>= $200B)
>= 10_000_000_000_00   → 'large'   (>= $10B)
>= 2_000_000_000_00    → 'mid'     (>= $2B)
>= 300_000_000_00      → 'small'   (>= $300M)
else                   → 'micro'
```

---

## 3. `router.py` — API Endpoints

All routes require JWT auth via `Depends(get_current_user)` from `app.auth.security`.

Wire into `main.py` with: `app.include_router(agents_router, prefix="/agents", dependencies=[Depends(get_current_user)])`

### Endpoints

**`POST /agents/ingest/{symbol}`**
- Calls `ingest_fundamentals(symbol, conn)`
- Returns: `{ symbol, periods_written, analyst_updated, elapsed_ms }`
- 404 if yfinance returns no data for symbol

**`GET /agents/fundamentals/{symbol}`**
- Returns structured fundamentals for the frontend:
```json
{
  "equity": { "symbol": "NVDA", "name": "...", "sector": "...", "industry": "..." },
  "annual": [ { "period_end": "2024-01-28", "fiscal_year": 2024, "revenue": 609000000000, ... } ],
  "quarterly": [ { "period_end": "2024-10-27", "fiscal_quarter": 3, ... } ],
  "ratios": { "pe_ratio": 35.2, "ev_ebitda": 28.1, ... },
  "analyst": { "target_low": 120.0, "target_mean": 165.0, "target_high": 220.0, "recommendation": "buy" },
  "fetched_at": "2024-11-01T12:00:00Z"
}
```
- Annual: latest 4 years, sorted descending by period_end
- Quarterly: latest 8 quarters, sorted descending by period_end
- Ratios: from the most recent quarterly period's ratio columns + .info valuation
- 404 if symbol not in equities table

**`GET /agents/equity/{symbol}`**
- Returns equity metadata only (for the page header):
```json
{ "symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "sector": "Information Technology", "industry": "Semiconductors & Semiconductor Equipment", "market_cap_tier": "mega", "is_tracked": true }
```

**`POST /agents/ingest/batch`**
- Body: `{ "symbols": ["HOOD", "NVDA", "KO"] }`
- Runs `ingest_fundamentals` for each symbol concurrently (asyncio.gather)
- Returns: `{ "results": [{ "symbol": "NVDA", "status": "ok", "periods_written": 12 }, ...] }`
- Per-symbol errors do not fail the batch — captured in `status: "error", "error": "...""`

**`GET /agents/search?q={query}`**
- Fuzzy search on symbol + name:
```sql
SELECT symbol, name, gics_sector, market_cap_tier
FROM equities
WHERE symbol ILIKE $1 OR name ILIKE $1
ORDER BY is_tracked DESC, symbol
LIMIT 10
```
- `$1` = `f'%{query}%'`

---

## 4. `models.py` — Pydantic Response Models

```python
class EquityMeta(BaseModel): ...
class FundamentalPeriod(BaseModel): ...  # one row
class AnalystData(BaseModel): ...
class RatiosData(BaseModel): ...
class FundamentalsResponse(BaseModel):
    equity: EquityMeta
    annual: list[FundamentalPeriod]
    quarterly: list[FundamentalPeriod]
    ratios: RatiosData
    analyst: AnalystData | None
    fetched_at: datetime | None

class IngestResult(BaseModel): ...
class BatchIngestResponse(BaseModel): ...
class SearchResult(BaseModel): ...
```

---

## 5. Wire into `main.py`

Add after the existing router imports:
```python
from app.agents.router import router as agents_router
# ...
app.include_router(agents_router, prefix="/agents", dependencies=_auth_dep)
```

---

## Notes

- yfinance is synchronous — wrap calls in `asyncio.get_event_loop().run_in_executor(None, ...)` to avoid blocking the event loop
- Handle `KeyError` and `AttributeError` gracefully — yfinance field names change without warning
- Log `[ingest] {symbol}: {periods_written} periods written` on success
- Never store `NaN` in the DB — always normalize to `None` before upsert
