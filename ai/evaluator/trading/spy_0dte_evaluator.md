# Evaluator: SPY 0DTE–5DTE Options Trading Job

**Version:** 1.0
**Module:** `backend/app/trading/`
**Paired generator:** `ai/generator/trading/spy_0dte_generator.md`

Score each check: ✅ pass | ❌ fail | ⚠️ partial

---

## A. File Structure (5 checks)

- [ ] A1. `backend/app/trading/__init__.py` exists
- [ ] A2. `backend/app/trading/strategy.py` exists
- [ ] A3. `backend/app/trading/job.py` exists
- [ ] A4. `backend/app/trading/state.py` exists
- [ ] A5. `backend/app/trading/models.py` exists
- [ ] A6. `backend/app/trading/router.py` exists
- [ ] A7. `backend/tests/test_trading_strategy.py` exists with ≥17 tests
- [ ] A8. `backend/tests/test_trading_job.py` exists with ≥9 tests

---

## B. Strategy Logic — ORB Computation (4 checks)

- [ ] B1. `compute_orb()` filters bars to 9:30–10:00 ET window only
- [ ] B2. Returns `None` when fewer than 5 bars are available
- [ ] B3. Returns `None` when ORB width < $0.10 (thin range guard)
- [ ] B4. `ORBLevels.high`, `.low`, `.width`, `.established_at` all populated correctly

---

## C. Strategy Logic — Entry Signal (5 checks)

- [ ] C1. CALL entry requires price > ORB high (not ≥, strict greater)
- [ ] C2. PUT entry requires price < ORB low (strict less)
- [ ] C3. Requires `signal_streak[direction] >= 2` before entering (whipsaw guard)
- [ ] C4. Blocks entry if `entry_counts[direction] >= 3`
- [ ] C5. Blocks CALL entry if a CALL position already open (no pyramiding)

---

## D. Strategy Logic — Exit Conditions (4 checks)

- [ ] D1. Take-profit fires at mark ≥ entry_premium × 1.80
- [ ] D2. Stop-loss fires at mark ≤ entry_premium × 0.45
- [ ] D3. Time stop fires at 15:45 ET regardless of P&L
- [ ] D4. `should_exit()` returns `(bool, reason_string)` — reason is one of: `take_profit | stop_loss | time_stop | hold`

---

## E. Position Sizing (3 checks)

- [ ] E1. `risk_per_trade = portfolio_value × 0.03`
- [ ] E2. `contracts = floor(risk_per_trade / (ask_price × 100))`
- [ ] E3. Result clamped to range `[1, 10]`

---

## F. Contract Symbol (2 checks)

- [ ] F1. Format: `SPY{YYMMDD}{C|P}{strike×1000 zero-padded to 8 digits}`
- [ ] F2. Example: SPY call, expiry 2024-06-07, strike $530 → `SPY240607C00530000`

---

## G. Job Lifecycle (5 checks)

- [ ] G1. `job.start()` is idempotent — calling twice creates only one asyncio Task
- [ ] G2. `job.stop()` cancels the asyncio Task and sets `state.status = "stopped"`
- [ ] G3. On `CancelledError`, job attempts to exit all open positions before returning
- [ ] G4. `_tick()` exceptions are caught, logged to `state.errors` (capped at 10), loop continues
- [ ] G5. `_tick()` skips all logic if current ET time is outside 09:30–16:00

---

## H. Alpaca Integration (5 checks)

- [ ] H1. All Alpaca HTTP calls use `httpx.AsyncClient` (not synchronous `alpaca-py` SDK)
- [ ] H2. Paper trading base URL: `https://paper-api.alpaca.markets` (from env with default)
- [ ] H3. Auth headers: `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`
- [ ] H4. Orders use `POST /v2/orders` with `type: "market"`, `time_in_force: "day"`
- [ ] H5. Alpaca HTTP errors (non-2xx) are caught and logged — do not crash the job loop

---

## I. API Endpoints (5 checks)

- [ ] I1. `POST /trading/start` → 200 + `JobStatusResponse`
- [ ] I2. `POST /trading/stop` → 200 + `JobStatusResponse`
- [ ] I3. `GET /trading/status` → `JobStatusResponse` with all fields present
- [ ] I4. `GET /trading/log` → list of `TradeLogEntry`, max 100 entries
- [ ] I5. `POST /trading/reset` → stops job + clears state → `JobStatusResponse` with `status: "idle"`

---

## J. Auth & Safety (4 checks)

- [ ] J1. All `/trading/*` endpoints protected by JWT (`Depends(get_current_user)`)
- [ ] J2. Router registered in `main.py` with `dependencies=_auth_dep`
- [ ] J3. No env variable named `ALPACA_REAL_*` is ever read in the trading module — paper only
- [ ] J4. No order is placed outside 09:30–15:45 ET — enforced in `_tick()` with hard time gate

---

## K. Test Coverage (5 checks)

- [ ] K1. All 17 strategy unit tests in `test_trading_strategy.py` pass with no I/O
- [ ] K2. All 9 job/API tests in `test_trading_job.py` pass
- [ ] K3. No test requires real Alpaca credentials
- [ ] K4. All `pytest` pass inside Docker container: `docker exec loaded-backend-1 pytest tests/test_trading_strategy.py tests/test_trading_job.py -v`
- [ ] K5. Pre-commit hooks pass (ruff format, ruff lint, mypy, pytest)

---

## Scoring

| Section | Checks | Weight |
|---|---|---|
| A. File Structure | 8 | 1× |
| B. ORB Computation | 4 | 2× |
| C. Entry Signal | 5 | 2× |
| D. Exit Conditions | 4 | 2× |
| E. Position Sizing | 3 | 1× |
| F. Contract Symbol | 2 | 1× |
| G. Job Lifecycle | 5 | 2× |
| H. Alpaca Integration | 5 | 2× |
| I. API Endpoints | 5 | 1× |
| J. Auth & Safety | 4 | 3× |
| K. Test Coverage | 5 | 2× |

**Passing threshold: 90% weighted score. All J (Auth & Safety) checks must pass — no exceptions.**

---

## Verification Commands

```bash
# 1. Strategy unit tests
docker exec loaded-backend-1 pytest tests/test_trading_strategy.py -v

# 2. Job + API tests
docker exec loaded-backend-1 pytest tests/test_trading_job.py -v

# 3. Start the job (paper)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=vsriddhi@gmail.com&password=Rizing%23" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/trading/start -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 4. Check status
curl -s http://localhost:8000/trading/status -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 5. Verify no real money creds used
grep -r "ALPACA_REAL" backend/app/trading/ && echo "FAIL: real creds found" || echo "PASS: paper only"

# 6. Verify time gate in source
grep -n "15:45\|15:30\|close_all" backend/app/trading/job.py

# 7. Stop job
curl -s -X POST http://localhost:8000/trading/stop -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
