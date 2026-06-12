# Generator — `portfolio` module, core (TRACK pillar)

Build the per-user portfolio system: portfolios, transactions, derived holdings,
Alpaca-paper sync, and the /portfolio UI. This is books-and-records only — the
module NEVER places orders anywhere (read-only Alpaca calls). Everything user-facing
is labeled "Heuristic, educational — not financial advice."

## Module layout

```
backend/app/portfolio/
  __init__.py
  models.py     Pydantic request/response models
  math.py       PURE money math (no I/O): derive_holdings, validation
  db.py         asyncpg helpers — every query scoped by owner_id
  sync.py       Alpaca paper account → synced portfolio (read-only)
  router.py     /portfolio endpoints (JWT; mounted with _auth_dep in main.py)
```

## Schema (DB_MIGRATIONS in backend/app/main.py)

- `portfolios`: id SERIAL PK, owner_id INT NOT NULL REFERENCES users(id) ON DELETE
  CASCADE, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'manual'
  ('manual'|'alpaca_paper'), cost_method TEXT NOT NULL DEFAULT 'average',
  base_currency TEXT NOT NULL DEFAULT 'USD', cash_cents BIGINT NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, last_synced_at TIMESTAMPTZ,
  created_at/updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(); UNIQUE(owner_id, name);
  partial unique index `uq_portfolios_owner_alpaca ON portfolios(owner_id) WHERE
  kind='alpaca_paper'` (one synced portfolio per user).
- `portfolio_transactions`: id SERIAL PK, portfolio_id FK ON DELETE CASCADE,
  symbol TEXT (NULL for cash-only types), tx_type TEXT NOT NULL
  (buy|sell|dividend|deposit|withdrawal), qty NUMERIC(18,6), price_cents BIGINT,
  amount_cents BIGINT NOT NULL (signed cash effect: buy negative,
  sell/dividend/deposit positive, withdrawal negative), fees_cents BIGINT NOT NULL
  DEFAULT 0, trade_date DATE NOT NULL, note TEXT, source TEXT NOT NULL DEFAULT
  'manual', external_id TEXT, created_at TIMESTAMPTZ DEFAULT NOW();
  UNIQUE(portfolio_id, external_id); index (portfolio_id, trade_date, id).
- `portfolio_holdings`: (portfolio_id, symbol) PK, qty NUMERIC(18,6) NOT NULL,
  avg_cost_cents BIGINT NOT NULL, cost_basis_cents BIGINT NOT NULL,
  realized_pnl_cents BIGINT NOT NULL DEFAULT 0 (lifetime per symbol),
  first_acquired DATE, updated_at TIMESTAMPTZ DEFAULT NOW(). This is a DERIVED
  CACHE: for manual portfolios it is rebuilt from the full transaction list inside
  the same DB transaction as any tx mutation; for alpaca_paper portfolios it is
  written directly from broker positions.
- `portfolio_snapshots`: (portfolio_id, snapshot_date) PK, equity_value_cents,
  cash_cents, total_value_cents, net_flow_cents (that day's deposits−withdrawals),
  realized_pnl_cents (cumulative), unrealized_pnl_cents, holdings_count INT,
  detail JSONB, created_at. (Populated by the P2 snapshot job; the table +
  manual POST /portfolio/{id}/snapshot endpoint ship now.)

## Money & quantity discipline

- DB stores integer cents (BIGINT). Quantities are NUMERIC(18,6) ↔ Decimal in
  Python (fractional shares supported).
- API accepts/returns DOLLARS as floats (matches fundamentals responses);
  convert at the boundary only: `_cents(dollars: float) -> int` =
  round(dollars*100), `_dollars(cents: int) -> float` = cents/100.
- One rounding point per cents boundary, ROUND_HALF_EVEN on Decimal→cents.

## math.py (pure, no I/O)

- `Holding` dataclass-ish dict: {symbol, qty: Decimal, avg_cost_cents: int,
  cost_basis_cents: int, realized_pnl_cents: int, first_acquired: date|None}.
- `derive_holdings(txs: list[Tx]) -> dict[str, Holding]` where txs are ordered by
  (trade_date, id). Rules:
  - buy: new_avg = (qty*avg + buy_qty*price + fees) / (qty + buy_qty), rounded to
    cents; cost_basis = round(qty_new * new_avg); first_acquired set on 0→positive.
  - sell: realized += round(sell_qty*(price − avg)) − fees; qty −= sell_qty;
    avg unchanged; cost_basis = round(qty * avg). Selling to zero keeps the symbol's
    lifetime realized_pnl; a later rebuy starts fresh basis at the new price.
  - dividend: cash income only (validated symbol optional) — never touches basis.
  - deposit/withdrawal: ignored here (cash handled at portfolio level).
  - Raises ValueError("oversell") if any sell exceeds held qty at that point.
- `cash_after(txs, starting_cents=0) -> int`: sum of amount_cents; raises
  ValueError("overdraw") if any prefix sum < 0.
- `validate_transaction(existing_txs, new_tx)`: runs both checks on the would-be
  sequence; the router converts ValueError → HTTP 422 with the reason.

## db.py

- All reads/writes parameterized asyncpg; EVERY portfolio access begins with
  `SELECT ... FROM portfolios WHERE id=$1 AND owner_id=$2` — missing row → caller
  raises 404 (no existence leak). Admin role gets no special access here (personal
  finance data).
- `rebuild_holdings(conn, portfolio_id)`: load txs ordered, derive_holdings, DELETE
  + executemany INSERT of portfolio_holdings, update portfolios.cash_cents from
  cash_after + updated_at — all inside the caller's transaction.
- `insert_transaction(...)` and `delete_transaction(...)` wrap: validate → mutate →
  rebuild_holdings in ONE conn.transaction().

## sync.py (Alpaca paper → portfolio, READ-ONLY)

- Reuse the existing alpaca client layer (app/alpaca) — get positions + account for
  the PAPER account only. Never import or call any order-placing function.
- `sync_alpaca_paper(pool, owner_id) -> SyncResult`: upsert the single
  kind='alpaca_paper' portfolio (name "Alpaca Paper"); in one DB transaction:
  DELETE holdings, INSERT from positions (qty Decimal, avg_entry_price→cents,
  realized_pnl_cents=0), set cash_cents from account cash, last_synced_at=NOW().
  Transactions are NOT fabricated; the synced portfolio's tx list stays empty and
  mutating endpoints return 409 for kind='alpaca_paper'.
- Missing Alpaca credentials → raise a clear error the router maps to 503.

## router.py — prefix /portfolio, all owner-scoped

- POST `/portfolio` {name} → 201 PortfolioOut; 409 duplicate name.
- GET `/portfolio` → list with live values: for each portfolio, holdings valued via
  resolve_price (import from app.fundamentals.price_fallback; annotate local
  `resolved: tuple[float, int, str] | None` — cross-module imports are Any under
  the pre-commit mypy) with per-symbol failure tolerance (price None → value via
  avg cost, flag stale=true).
- GET `/portfolio/{id}` → detail: portfolio + valued holdings + totals
  (equity_value, cash, total_value, unrealized_pnl, realized_pnl).
- PATCH `/portfolio/{id}` {name?, is_active?} → updated; DELETE → 204 cascade.
- POST `/portfolio/{id}/transactions` {symbol?, tx_type, qty?, price?, fees?,
  trade_date, note?} (dollars) → 201 {transaction, holding|null};
  422 oversell/overdraw/bad shape (e.g. buy without symbol/qty/price);
  409 when portfolio kind='alpaca_paper'.
- GET `/portfolio/{id}/transactions?symbol&limit=50&offset=0` → {total, items}.
- DELETE `/portfolio/{id}/transactions/{tx_id}` → 204 (validate the remaining
  sequence still derives cleanly; else 422).
- GET `/portfolio/{id}/holdings` → rows incl. live price, market_value,
  unrealized_pnl(+pct), weight_pct, realized_pnl, name+sector from equities (LEFT
  JOIN; unknown symbol → nulls, never crash).
- POST `/portfolio/sync/alpaca` → {portfolio_id, positions_synced, cash, as_of};
  503 when creds missing.
- POST `/portfolio/{id}/snapshot` → compute + upsert today's snapshot row (valuing
  like /holdings), return it. (Scheduler arrives in P2.)
- GET `/portfolio/{id}/allocation` → {by_sector, by_symbol, concentration:
  {top1, top5, hhi, label diversified|moderate|concentrated}, cash_pct}.
- Every response model includes `disclaimer` where advice-adjacent (holdings,
  allocation): "Heuristic, educational — not financial advice."

## main.py wiring (exempt file)

DB_MIGRATIONS additions; `from app.portfolio.router import router as
portfolio_router`; `app.include_router(portfolio_router, dependencies=_auth_dep)`.

## Frontend (P1 scope)

- `frontend/src/app/portfolio/page.tsx`: portfolio cards (Card+Stat: total value,
  day change placeholder until snapshots, holdings count), create-portfolio inline
  form, "Sync Alpaca Paper" Button (busy state, error surface), click → drill.
- `frontend/src/app/portfolio/[id]/page.tsx`: Tabs Overview | Holdings |
  Transactions. Overview: Stat row (value/cash/unrealized/realized) + allocation
  BarChartView + concentration badges. Holdings: table (symbol, qty, avg cost,
  price, value, unrealized $ and %, weight, realized) with color-coded P&L.
  Transactions: list + entry form (type select, symbol, qty, price, fees, date,
  note) with 422 reasons surfaced; delete with confirm. Synced portfolios: entry
  form replaced by "synced from Alpaca Paper — read-only" notice + Sync Now button.
- Nav links "Portfolio" (before Macro) in frontend/src/app/page.tsx.
- Design system only (PageShell/Card/Stat/Badge/Tabs/Button/InfoTip,
  BarChartView); auth-gate pattern identical to /macro page; monospace data text.

## Tests (pre-commit per-file gate)

tests/test_portfolio_{models,math,db,sync,router}.py — see evaluator checklist for
the required cases. Pure math tests need no DB; db/router/sync tests mock asyncpg
(repo style: MagicMock pool/conn with AsyncMock methods, conftest auth bypass).

## Conventions

Python 3.11-safe (no nested same-quote f-strings); ruff + strict mypy clean
(typed locals at cross-module import boundaries); raw SQL only (no ORM);
logger per module; no print.
