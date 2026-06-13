# Generator: SPY 0DTE–5DTE Options Trading Job

**Version:** 1.0
**Module:** `backend/app/trading/`
**Scope:** Paper-trading autonomous job — Opening Range Breakout on SPY options (0DTE to 5DTE), runs continuously during market hours, managed via REST API.

---

## Strategy: Opening Range Breakout (ORB)

### Concept
Capture the directional move after SPY establishes its opening range. The first 30 minutes of trading define a high and low. A confirmed breakout above/below that range signals the direction for the session. We buy ATM options in the direction of the breakout.

### Signal Logic (run every 5 minutes via scheduler)

**Phase 1 — Opening Range Capture (9:30–10:00 ET)**
- Fetch 1-min SPY bars from Alpaca for the session so far
- ORB high = max(high) of bars from 9:30–10:00
- ORB low  = min(low)  of bars from 9:30–10:00
- ORB width = ORB high − ORB low (sanity check: reject if < $0.10)
- No trades placed during this phase

**Phase 2 — Entry Window (10:00–15:30 ET)**
- Every 5 min: fetch latest SPY price (last trade price)
- Entry signal rules:
  - **CALL signal**: last price > ORB high AND no open CALL position AND entry_count < 3
  - **PUT signal**: last price < ORB low AND no open PUT position AND entry_count < 3
  - Confirmation: signal must persist for 2 consecutive 5-min checks (avoids whipsaw)
- On confirmed signal → `_place_entry(direction)`

**Phase 3 — Exit Monitoring (runs same 5-min loop)**
- For each open position:
  - Fetch current option mark price from Alpaca
  - Take-profit trigger: mark ≥ entry_premium × 1.80 (80% gain)
  - Stop-loss trigger: mark ≤ entry_premium × 0.45 (55% loss)
  - Time stop: market close approach — close ALL positions at 15:45 ET regardless
- On trigger → `_place_exit(position)`

**Re-entry**: After a position is exited (profit or stop), entry_count increments. Max 3 entries per direction per day.

---

## Option Selection Logic (`_select_contract`)

```python
def _select_contract(direction: str, spy_price: float, dte_target: int) -> str:
    """Return the best option contract symbol for the given direction.

    Selection rules:
    1. Expiry: prefer 0DTE on Mon/Wed/Fri (SPY has daily expirations)
               prefer 1DTE (next trading day) on Tue/Thu
               If dte_target > 0, use that many days out instead
    2. Strike: ATM = round(spy_price) — no moneyness bias by default
    3. Contract symbol format: SPY{YYMMDD}{C|P}{strike×1000 zero-padded to 8 digits}
       Example: SPY240607C00530000 = SPY CALL exp 2024-06-07 strike $530
    4. Verify contract exists via Alpaca get_option_contracts() before placing order
       If exact ATM not found, walk ±$1 up to ±$5 to find the nearest listed contract
    """
```

---

## Position Sizing

```
account_equity    = from Alpaca GET /account → portfolio_value
risk_per_trade    = account_equity × 0.03        # 3% max risk per trade
premium_per_lot   = current ask price × 100       # 1 contract = 100 shares
contracts_to_buy  = floor(risk_per_trade / premium_per_lot)
contracts_to_buy  = max(1, min(contracts_to_buy, 10))  # floor 1, cap 10
```

---

## New Files

```
backend/app/trading/
    __init__.py
    strategy.py     ← ORB signal logic, contract selection, position sizing
    job.py          ← AsyncIO scheduler loop (runs every 5 min during market hours)
    state.py        ← In-memory job state (ORB levels, open positions, entry counts)
    models.py       ← Pydantic models for API + internal state
    router.py       ← FastAPI router /trading/*

backend/tests/
    test_trading_strategy.py   ← unit tests (all mocked)
    test_trading_job.py        ← job lifecycle tests (mocked)
```

---

## 1. `backend/app/trading/state.py`

Thread-safe in-memory state for one trading session. Resets at midnight ET or on job restart.

```python
@dataclass
class ORBLevels:
    high: float
    low: float
    width: float
    established_at: datetime

@dataclass
class OpenPosition:
    contract_symbol: str
    direction: str          # "CALL" | "PUT"
    contracts: int
    entry_premium: float    # per-share price paid (e.g. $2.50)
    entry_order_id: str
    opened_at: datetime

@dataclass
class TradingState:
    status: str             # "idle" | "capturing_orb" | "trading" | "closed" | "stopped"
    orb: ORBLevels | None
    open_positions: list[OpenPosition]
    entry_counts: dict      # {"CALL": 0, "PUT": 0}
    daily_pnl_cents: int    # running P&L in cents for the session
    session_date: date
    last_tick_at: datetime | None
    signal_streak: dict     # {"CALL": 0, "PUT": 0} — consecutive confirmations
    errors: list[str]       # last 10 errors for status display
```

Single module-level instance: `trading_state = TradingState(...)`. Protected by `asyncio.Lock`.

---

## 2. `backend/app/trading/strategy.py`

Pure functions — no I/O, no side effects. Takes data as arguments, returns decisions.

```python
def compute_orb(bars: list[dict]) -> ORBLevels | None:
    """Given 1-min bars for 9:30–10:00, return ORB levels or None if insufficient data."""

def should_enter(
    direction: str,
    spy_price: float,
    orb: ORBLevels,
    open_positions: list[OpenPosition],
    entry_counts: dict,
    signal_streak: dict,
) -> bool:
    """Return True if entry conditions are met for this direction."""

def should_exit(
    position: OpenPosition,
    current_mark: float,
    current_time: datetime,
) -> tuple[bool, str]:
    """Return (should_exit, reason). reason: 'take_profit'|'stop_loss'|'time_stop'|'hold'"""

def select_strike(spy_price: float, direction: str) -> int:
    """Return ATM strike as integer dollar amount."""

def size_position(portfolio_value: float, ask_price: float) -> int:
    """Return number of contracts (1–10)."""

def format_contract_symbol(expiry: date, direction: str, strike: int) -> str:
    """Return OCC symbol: SPY{YYMMDD}{C|P}{strike×1000 padded to 8 digits}."""
```

---

## 3. `backend/app/trading/job.py`

Async scheduler. Uses `asyncio` — no external scheduler libraries (APScheduler etc.).

```python
class TradingJob:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the trading loop. Idempotent — no-op if already running."""

    async def stop(self) -> None:
        """Stop the trading loop gracefully. Cancels the asyncio task."""

    async def _loop(self) -> None:
        """Main loop. Runs every 5 min. Exits at 16:00 ET or on stop()."""

    async def _tick(self) -> None:
        """One iteration: fetch data → update ORB → check signals → manage exits."""

    async def _fetch_spy_price(self) -> float:
        """GET latest SPY trade price from Alpaca market data API."""

    async def _fetch_spy_bars(self, start: datetime, end: datetime) -> list[dict]:
        """GET 1-min SPY bars from Alpaca. Returns list of {time, open, high, low, close}."""

    async def _place_entry(self, direction: str) -> None:
        """Select contract → size position → place market buy order via Alpaca."""

    async def _place_exit(self, position: OpenPosition, reason: str) -> None:
        """Place market sell order for the position via Alpaca."""
```

**Loop timing:**
- Sleep interval: 5 minutes between ticks
- Exception handling: catch all exceptions in `_tick`, log to `state.errors`, never crash the loop
- Market hours gate: skip tick if current ET time < 09:30 or > 16:00
- Graceful shutdown: on `asyncio.CancelledError`, place exit orders for all open positions before returning

**Alpaca calls:**
- Use `httpx.AsyncClient` directly against Alpaca REST API — do NOT use the synchronous `alpaca-py` SDK in the async loop
- Base URL: `https://paper-api.alpaca.markets` (paper) — read from env `ALPACA_PAPER_BASE_URL` with this default
- Auth header: `APCA-API-KEY-ID: {ALPACA_PAPER_API_KEY}`, `APCA-API-SECRET-KEY: {ALPACA_PAPER_SECRET_KEY}`
- Market data: `https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Min&start=...&end=...`
- Options data: `https://data.alpaca.markets/v1beta1/options/snapshots/SPY`
- Place order: `POST https://paper-api.alpaca.markets/v2/orders`

---

## 4. `backend/app/trading/models.py`

```python
class JobStatusResponse(BaseModel):
    status: str                   # "idle" | "capturing_orb" | "trading" | "closed" | "stopped"
    session_date: str | None
    orb_high: float | None
    orb_low: float | None
    open_positions: list[PositionSummary]
    entry_counts: dict            # {"CALL": 0, "PUT": 0}
    daily_pnl_usd: float          # daily_pnl_cents / 100
    last_tick_at: str | None
    recent_errors: list[str]

class PositionSummary(BaseModel):
    contract_symbol: str
    direction: str
    contracts: int
    entry_premium: float
    current_mark: float | None
    unrealized_pnl_usd: float | None

class JobStartRequest(BaseModel):
    pass                          # future: strategy overrides

class TradeLogEntry(BaseModel):
    timestamp: str
    action: str                   # "entry" | "exit" | "orb_established" | "signal" | "error"
    direction: str | None
    contract_symbol: str | None
    contracts: int | None
    price: float | None
    reason: str | None
    pnl_usd: float | None
```

---

## 5. `backend/app/trading/router.py`

```
POST /trading/start      → JobStatusResponse     (start the job, idempotent)
POST /trading/stop       → JobStatusResponse     (stop gracefully)
GET  /trading/status     → JobStatusResponse     (current state snapshot)
GET  /trading/log        → list[TradeLogEntry]   (trade activity log, last 100)
POST /trading/reset      → JobStatusResponse     (stop + clear state, ready for new session)
```

All endpoints require JWT auth (same `Depends(get_current_user)` pattern).
Wire into `main.py`: `app.include_router(trading_router, prefix="/trading")` with auth dependency.

---

## 6. Register in `main.py`

```python
from app.trading.router import router as trading_router
app.include_router(trading_router, prefix="/trading", dependencies=_auth_dep)
```

---

## 7. Tests

### `backend/tests/test_trading_strategy.py`

Pure function tests — zero I/O, zero mocking needed.

```
test_compute_orb_normal          — 30 bars, valid ORB returned
test_compute_orb_insufficient    — <5 bars, returns None
test_compute_orb_reject_thin     — ORB width < $0.10, returns None
test_should_enter_call_breakout  — price above ORB high, streak=2, entry_count<3 → True
test_should_enter_no_signal      — price inside ORB → False
test_should_enter_max_entries    — entry_count=3 → False regardless of price
test_should_enter_already_open   — open CALL position → False for CALL, True for PUT
test_should_enter_streak_too_low — streak=1 → False (need 2 consecutive)
test_should_exit_take_profit     — mark = entry × 1.81 → (True, 'take_profit')
test_should_exit_stop_loss       — mark = entry × 0.44 → (True, 'stop_loss')
test_should_exit_time_stop       — time = 15:46 ET → (True, 'time_stop')
test_should_exit_hold            — mark in range, time before 15:45 → (False, 'hold')
test_size_position_normal        — $100k portfolio, $3.00 ask → 10 contracts (capped)
test_size_position_small_acct    — $10k portfolio, $5.00 ask → 6 contracts
test_size_position_min_1         — very expensive option → always at least 1
test_format_contract_symbol_call — date=2024-06-07, CALL, strike=530 → SPY240607C00530000
test_format_contract_symbol_put  — date=2024-06-07, PUT, strike=529 → SPY240607P00529000
```

### `backend/tests/test_trading_job.py`

Job lifecycle tests — mock Alpaca HTTP calls with `respx` or `unittest.mock.patch`.

```
test_job_start_sets_status_capturing_orb   — start() → state.status == "capturing_orb"
test_job_start_idempotent                  — start() twice → only one task
test_job_stop_sets_status_stopped          — stop() → state.status == "stopped"
test_tick_during_orb_window_no_entry       — time=9:45, orb not set → no entry called
test_tick_after_orb_signal_call            — orb set, price > orb.high, streak=2 → _place_entry("CALL") called
test_tick_exit_take_profit                 — open position, mark=entry×1.9 → _place_exit called
test_api_start_endpoint                    — POST /trading/start → 200 + JobStatusResponse
test_api_status_endpoint                   — GET /trading/status → fields present
test_api_stop_endpoint                     — POST /trading/stop → 200 + status="stopped"
test_api_reset_endpoint                    — POST /trading/reset → status="idle"
```

---

## What NOT to Do

- Do NOT use real money credentials — always paper (`ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_SECRET_KEY`)
- Do NOT use synchronous `alpaca-py` SDK inside the async job loop — use `httpx.AsyncClient`
- Do NOT persist state to DB in v1 — in-memory only (trade log stored in `state.py` list)
- Do NOT implement complex Greeks-based sizing in v1 — ATM strike + flat position size
- Do NOT support multiple simultaneous strategies — one job instance at a time
- Do NOT auto-start the job on server boot — always manual `POST /trading/start`
- Do NOT place orders outside 9:30–15:45 ET window — enforce in `_tick` with hard gate
