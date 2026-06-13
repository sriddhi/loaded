# Evaluator — `portfolio` module, core (TRACK pillar)

Score each ❌/✅. All ❌ fixed before done.

## Money math (each unit-tested)
- [ ] Average cost over multiple buys incl. fees matches hand-computed fixture to
      the cent; one rounding point per cents boundary (ROUND_HALF_EVEN).
- [ ] Partial sell: realized = qty·(price−avg)−fees with correct sign; avg
      unchanged; cost basis shrinks proportionally.
- [ ] Sell-to-zero then rebuy: basis resets to new price, lifetime realized
      preserved; oversell raises → API 422; cash overdraw (prefix sum < 0) → 422.
- [ ] Dividend adds cash income only (basis untouched); deposit/withdrawal move
      cash only; fractional shares (Decimal qty) exact.

## Data integrity
- [ ] Transactions are the single source of truth (manual portfolios); holdings
      rebuilt inside the SAME DB transaction as every tx insert/delete.
- [ ] Deleting a historical tx revalidates the remaining sequence (422 if it would
      imply a negative position at any point).
- [ ] All money columns integer cents; dollars only at the API boundary.

## Auth & safety
- [ ] Every query owner-scoped; another user's portfolio → 404 (no existence
      leak) — covered by a two-user router test.
- [ ] alpaca_paper portfolios reject tx mutations with 409; sync is read-only
      (no order-placing import/call anywhere in the module).
- [ ] Module never places trades; no real-account access; creds missing → 503.
- [ ] Advice-adjacent responses carry the "not financial advice" disclaimer.

## Sync correctness
- [ ] Re-sync idempotent (no duplicate portfolio/holdings; partial unique index);
      position gone at broker → row removed locally; float→cents via boundary
      helper; account cash mirrored.

## API behavior
- [ ] CRUD paths: 201/200/204; 409 duplicate name; 422 invalid tx shapes; holdings
      tolerate unknown symbols + price failures (stale flag, no crash).
- [ ] Allocation: weights sum ≈ 100% of equity; HHI + top1/top5 + label bands;
      snapshot endpoint upserts (one row per day).

## UI
- [ ] /portfolio + /portfolio/[id] render with data and with empty portfolios (no
      broken states); synced portfolio shows read-only notice; 422 reasons surfaced
      on the tx form; nav links present; design-system components only.

## Code quality
- [ ] ruff + strict mypy clean (incl. hook invocation from repo root); tests per
      app file; Python 3.11-compatible; pure math importable without DB.
