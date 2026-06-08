# Evaluator: Fundamentals Data Pipeline

**Module:** `backend/app/agents/`
**Paired with:** `ai/generator/agents/fundamentals_generator.md`
**Run after build. All ❌ must be fixed before feature is complete.**

---

## How to Run

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=vsriddhi@gmail.com&password=Rizing%23" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Ingest all 3 tickers
curl -s -X POST http://localhost:8000/agents/ingest/batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["HOOD", "NVDA", "KO"]}' | python3 -m json.tool

# Run unit tests
cd backend && pytest tests/test_agents_fundamentals.py -v
```

---

## Checks

### A — File Structure
- [ ] A1: `backend/app/agents/__init__.py` exists
- [ ] A2: `backend/app/agents/data.py` exists with `fetch_fundamentals` function
- [ ] A3: `backend/app/agents/ingest.py` exists with `ingest_fundamentals` function
- [ ] A4: `backend/app/agents/router.py` exists with all 5 endpoints
- [ ] A5: `backend/app/agents/models.py` exists with all Pydantic models
- [ ] A6: `backend/tests/test_agents_fundamentals.py` exists with ≥ 8 test functions

### B — API Endpoints
- [ ] B1: `POST /agents/ingest/NVDA` returns 200 with `{ symbol, periods_written, elapsed_ms }`
- [ ] B2: `POST /agents/ingest/HOOD` returns 200
- [ ] B3: `POST /agents/ingest/KO` returns 200
- [ ] B4: `POST /agents/ingest/FAKEXYZ` returns 404
- [ ] B5: `GET /agents/fundamentals/NVDA` returns 200 with `annual`, `quarterly`, `ratios`, `analyst` keys
- [ ] B6: `GET /agents/fundamentals/FAKEXYZ` returns 404
- [ ] B7: `GET /agents/equity/NVDA` returns 200 with `symbol`, `name`, `sector`, `industry`, `market_cap_tier`
- [ ] B8: `POST /agents/ingest/batch` with `["HOOD","NVDA","KO"]` returns 200 with `results` array of 3
- [ ] B9: `GET /agents/search?q=NV` returns NVDA in results
- [ ] B10: All endpoints return 401 without Authorization header

### C — Data Completeness (NVDA, run after ingest)
```bash
docker compose exec postgres psql -U loaded -c \
  "SELECT count(*) FROM fundamentals WHERE equity_id=(SELECT id FROM equities WHERE symbol='NVDA')"
```
- [ ] C1: NVDA fundamentals row count ≥ 12 (4 annual + 8 quarterly)
- [ ] C2: HOOD fundamentals row count ≥ 4 (fewer history available)
- [ ] C3: KO fundamentals row count ≥ 12
- [ ] C4: NVDA annual rows have `revenue IS NOT NULL`
- [ ] C5: NVDA quarterly rows have `eps_diluted IS NOT NULL`
- [ ] C6: Analyst estimates table has ≥ 1 row per tracked ticker

### D — Integer Cents (NON-NEGOTIABLE)
```bash
docker compose exec postgres psql -U loaded -c \
  "SELECT revenue, gross_profit, total_assets FROM fundamentals WHERE equity_id=(SELECT id FROM equities WHERE symbol='NVDA') LIMIT 1"
```
- [ ] D1: NVDA revenue > 1_000_000_000_000 (i.e., stored in cents, not dollars — $60B+ → >6_000_000_000_000)
- [ ] D2: Revenue is an integer (no decimal point in output)
- [ ] D3: `total_assets` is BIGINT (no float drift)
- [ ] D4: `eps_diluted` is a small decimal (e.g., 1.25 — NOT stored in cents)
- [ ] D5: `to_cents(None)` returns `None` (no crash)
- [ ] D6: `to_cents(float('nan'))` returns `None` (no crash)

### E — Ratio Computation
```bash
docker compose exec postgres psql -U loaded -c \
  "SELECT gross_margin, operating_margin, net_margin, roic, free_cash_flow FROM fundamentals WHERE equity_id=(SELECT id FROM equities WHERE symbol='NVDA') AND period_type='annual' ORDER BY period_end DESC LIMIT 1"
```
- [ ] E1: `gross_margin` is between 0.0 and 1.0
- [ ] E2: `gross_margin` ≈ `gross_profit / revenue` (within 0.002 tolerance)
- [ ] E3: `free_cash_flow` = `operating_cash_flow + capex` (capex is negative → FCF < OCF)
- [ ] E4: `roic` is not NULL and between -1.0 and 10.0 (reasonable range)
- [ ] E5: Ratios are NULL (not 0 or NaN) when denominator is zero

### F — Idempotency
- [ ] F1: Running `POST /agents/ingest/NVDA` twice produces the same row count (no duplicates)
```bash
COUNT1=$(docker compose exec postgres psql -U loaded -t -c "SELECT count(*) FROM fundamentals WHERE equity_id=(SELECT id FROM equities WHERE symbol='NVDA')")
curl -s -X POST http://localhost:8000/agents/ingest/NVDA -H "Authorization: Bearer $TOKEN" > /dev/null
COUNT2=$(docker compose exec postgres psql -U loaded -t -c "SELECT count(*) FROM fundamentals WHERE equity_id=(SELECT id FROM equities WHERE symbol='NVDA')")
echo "Before: $COUNT1 After: $COUNT2"  # must be equal
```
- [ ] F2: `fetched_at` is updated on re-ingest (not stuck at first-run time)

### G — Unit Tests
```bash
cd backend && pytest tests/test_agents_fundamentals.py -v
```
- [ ] G1: Test `to_cents` with positive, negative, None, NaN inputs
- [ ] G2: Test `gross_margin` computation (mock: gross_profit=50, revenue=100 → 0.5)
- [ ] G3: Test `free_cash_flow` computation (mock: ocf=80, capex=-20 → 60)
- [ ] G4: Test `revenue_growth_yoy` (mock: rev_t=120, rev_t4=100 → 0.2)
- [ ] G5: Test upsert idempotency (insert row twice, count = 1)
- [ ] G6: Test `GET /agents/fundamentals/FAKEXYZ` returns 404
- [ ] G7: Test all endpoints return 401 without token
- [ ] G8: Test batch ingest returns one result per symbol

### H — No Float Money in DB
```bash
docker compose exec postgres psql -U loaded -c "\d fundamentals" | grep -E "revenue|assets|debt|equity|cash"
```
- [ ] H1: `revenue` column type is `bigint`
- [ ] H2: `total_assets` column type is `bigint`
- [ ] H3: `total_debt` column type is `bigint`
- [ ] H4: `gross_profit` column type is `bigint`
- [ ] H5: `eps_diluted` column type is `numeric` (not bigint)

### I — Event loop safety
- [ ] I1: yfinance calls are wrapped in `run_in_executor` (not called directly in async function)
- [ ] I2: Backend logs no `RuntimeWarning: coroutine was never awaited` during ingest

### J — Integration (end-to-end)
```bash
# Frontend must be able to use the data
curl -s http://localhost:8000/agents/fundamentals/NVDA -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert len(d['annual']) >= 4, f'Expected 4 annual, got {len(d[\"annual\"])}'
assert len(d['quarterly']) >= 8, f'Expected 8 quarterly, got {len(d[\"quarterly\"])}'
assert d['ratios']['pe_ratio'] is not None, 'PE ratio missing'
assert d['analyst'] is not None, 'Analyst data missing'
print('✅ All integration checks passed')
"
```
- [ ] J1: Script above runs without assertion errors for NVDA
- [ ] J2: Script above runs without assertion errors for KO
- [ ] J3: Script above runs without assertion errors for HOOD

---

## Score

Count ✅ / total checks. Feature is **done** when score = 100% or all failures are documented with a known external limitation (e.g., yfinance doesn't provide EPS for HOOD before IPO).

Save result to `ai/benchmarks/results/fundamentals_YYYY-MM-DD.json`.
