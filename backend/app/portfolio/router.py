"""FastAPI router for /portfolio — per-user books & records. Never places orders."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import asyncpg
from app.auth.security import get_current_user
from app.portfolio import db as pdb
from app.portfolio.math import concentration, weights
from app.portfolio.models import (
    DISCLAIMER,
    AllocationOut,
    ConcentrationOut,
    HoldingOut,
    PortfolioCreate,
    PortfolioDetail,
    PortfolioOut,
    PortfolioPatch,
    SectorSlice,
    SnapshotOut,
    SymbolSlice,
    SyncResult,
    TransactionCreate,
    TransactionOut,
    TransactionPage,
    TransactionResult,
)
from app.portfolio.sync import AlpacaUnavailableError, sync_alpaca_paper
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _uid(user: dict[str, Any]) -> int:
    return int(user["id"])


async def _own(conn: asyncpg.Connection, pid: int, uid: int) -> asyncpg.Record:
    row = await pdb.get_portfolio(conn, pid, uid)
    if row is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return row


async def _price_for(symbol: str, request: Request) -> tuple[float | None, bool]:
    """Live price (dollars, stale flag); never raises — valuation falls back."""
    from app.fundamentals.price_fallback import resolve_price

    try:
        cache = getattr(request.app.state, "price_cache", None)
        resolved: tuple[float, int, str] | None = await resolve_price(symbol, cache)
    except Exception:  # noqa: BLE001
        return None, True
    if resolved is None:
        return None, True
    price = resolved[0]
    return float(price), False


def _tx_out(r: Any) -> TransactionOut:
    return TransactionOut(
        id=r["id"],
        portfolio_id=r["portfolio_id"],
        symbol=r["symbol"],
        tx_type=r["tx_type"],
        qty=float(r["qty"]) if r["qty"] is not None else None,
        price=pdb.dollars(r["price_cents"]) if r["price_cents"] is not None else None,
        amount=pdb.dollars(r["amount_cents"]),
        fees=pdb.dollars(r["fees_cents"]),
        trade_date=r["trade_date"],
        note=r["note"],
        source=r["source"],
        created_at=r["created_at"],
    )


async def _valued_holdings(
    request: Request, conn: asyncpg.Connection, pid: int
) -> list[HoldingOut]:
    rows = await pdb.load_holdings(conn, pid)
    out: list[HoldingOut] = []
    values: dict[str, int] = {}
    for r in rows:
        qty = float(r["qty"])
        price, stale = await _price_for(r["symbol"], request)
        avg = pdb.dollars(r["avg_cost_cents"])
        basis = pdb.dollars(r["cost_basis_cents"])
        mv = round(qty * price, 2) if price is not None else None
        values[r["symbol"]] = round((mv if mv is not None else basis) * 100)
        out.append(
            HoldingOut(
                symbol=r["symbol"],
                name=r["equity_name"],
                sector=r["sector"],
                qty=qty,
                avg_cost=avg,
                cost_basis=basis,
                price=price,
                price_stale=stale,
                market_value=mv,
                unrealized_pnl=round(mv - basis, 2) if mv is not None else None,
                unrealized_pct=round((mv / basis - 1) * 100, 2) if mv and basis else None,
                realized_pnl=pdb.dollars(r["realized_pnl_cents"]),
                first_acquired=r["first_acquired"],
            )
        )
    w = weights(values)
    for h in out:
        h.weight_pct = round(w.get(h.symbol, 0.0) * 100, 2)
    return out


def _portfolio_out(r: Any, holdings: list[HoldingOut] | None = None) -> PortfolioOut:
    base = PortfolioOut(
        id=r["id"],
        name=r["name"],
        kind=r["kind"],
        cash=pdb.dollars(r["cash_cents"]),
        is_active=r["is_active"],
        last_synced_at=r["last_synced_at"],
        created_at=r["created_at"],
    )
    if holdings is not None:
        equity = sum(h.market_value or h.cost_basis for h in holdings)
        base.holdings_count = len(holdings)
        base.equity_value = round(equity, 2)
        base.total_value = round(equity + base.cash, 2)
        base.unrealized_pnl = round(sum(h.unrealized_pnl or 0.0 for h in holdings), 2)
        base.realized_pnl = round(sum(h.realized_pnl for h in holdings), 2)
    return base


# ── Portfolio CRUD ────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=PortfolioOut)
async def create_portfolio(
    body: PortfolioCreate, request: Request, user: Any = Depends(get_current_user)
) -> PortfolioOut:
    async with _pool(request).acquire() as conn:
        try:
            row = await conn.fetchrow(
                "INSERT INTO portfolios (owner_id, name) VALUES ($1, $2) RETURNING *",
                _uid(user),
                body.name.strip(),
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(status_code=409, detail="Portfolio name already exists") from exc
    return _portfolio_out(row, [])


@router.get("", response_model=list[PortfolioOut])
async def list_portfolios(
    request: Request, user: Any = Depends(get_current_user)
) -> list[PortfolioOut]:
    async with _pool(request).acquire() as conn:
        rows = await pdb.list_portfolios(conn, _uid(user))
        out = []
        for r in rows:
            holdings = await _valued_holdings(request, conn, r["id"])
            out.append(_portfolio_out(r, holdings))
    return out


@router.get("/{pid}", response_model=PortfolioDetail)
async def get_portfolio(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> PortfolioDetail:
    async with _pool(request).acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        holdings = await _valued_holdings(request, conn, pid)
    base = _portfolio_out(row, holdings)
    return PortfolioDetail(**base.model_dump(), holdings=holdings)


@router.patch("/{pid}", response_model=PortfolioOut)
async def patch_portfolio(
    pid: int, body: PortfolioPatch, request: Request, user: Any = Depends(get_current_user)
) -> PortfolioOut:
    async with _pool(request).acquire() as conn:
        await _own(conn, pid, _uid(user))
        try:
            row = await conn.fetchrow(
                "UPDATE portfolios SET name = COALESCE($3, name), "
                "is_active = COALESCE($4, is_active), updated_at = NOW() "
                "WHERE id = $1 AND owner_id = $2 RETURNING *",
                pid,
                _uid(user),
                body.name.strip() if body.name else None,
                body.is_active,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(status_code=409, detail="Portfolio name already exists") from exc
    return _portfolio_out(row)


@router.delete("/{pid}", status_code=204)
async def delete_portfolio(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> None:
    async with _pool(request).acquire() as conn:
        await _own(conn, pid, _uid(user))
        await conn.execute(
            "DELETE FROM portfolios WHERE id = $1 AND owner_id = $2", pid, _uid(user)
        )


# ── Transactions ──────────────────────────────────────────────────────────────


def _validate_tx_shape(
    body: TransactionCreate,
) -> tuple[str | None, Decimal | None, int | None, int]:
    """Shape rules per tx_type. Returns (symbol, qty, price_cents, gross_cents)."""
    if body.tx_type in ("buy", "sell"):
        if not body.symbol or body.qty is None or body.price is None:
            raise HTTPException(
                status_code=422, detail=f"{body.tx_type} requires symbol, qty and price"
            )
        return (
            body.symbol.strip().upper(),
            Decimal(str(body.qty)),
            pdb.cents(body.price),
            0,
        )
    if body.amount is None:
        raise HTTPException(status_code=422, detail=f"{body.tx_type} requires amount")
    symbol = body.symbol.strip().upper() if body.symbol else None
    return symbol, None, None, pdb.cents(body.amount)


@router.post("/{pid}/transactions", status_code=201, response_model=TransactionResult)
async def add_transaction(
    pid: int, body: TransactionCreate, request: Request, user: Any = Depends(get_current_user)
) -> TransactionResult:
    symbol, qty, price_cents, gross_cents = _validate_tx_shape(body)
    async with _pool(request).acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        if row["kind"] != "manual":
            raise HTTPException(
                status_code=409, detail="Synced portfolio is read-only — re-sync instead"
            )
        async with conn.transaction():
            try:
                tx = await pdb.insert_transaction(
                    conn,
                    pid,
                    tx_type=body.tx_type,
                    symbol=symbol,
                    qty=qty,
                    price_cents=price_cents,
                    fees_cents=pdb.cents(body.fees),
                    gross_cents=gross_cents,
                    trade_date=body.trade_date,
                    note=body.note,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        holding = None
        if symbol:
            valued = await _valued_holdings(request, conn, pid)
            holding = next((h for h in valued if h.symbol == symbol), None)
    return TransactionResult(transaction=_tx_out(tx), holding=holding)


@router.get("/{pid}/transactions", response_model=TransactionPage)
async def list_transactions(
    pid: int,
    request: Request,
    symbol: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: Any = Depends(get_current_user),
) -> TransactionPage:
    async with _pool(request).acquire() as conn:
        await _own(conn, pid, _uid(user))
        where = "portfolio_id = $1" + (" AND symbol = $4" if symbol else "")
        args: list[Any] = [pid, limit, offset]
        if symbol:
            args.append(symbol.upper())
        total = await conn.fetchval(
            f"SELECT count(*) FROM portfolio_transactions WHERE {where}",  # noqa: S608
            *(a for i, a in enumerate(args) if i not in (1, 2)),
        )
        rows = await conn.fetch(
            f"SELECT * FROM portfolio_transactions WHERE {where} "  # noqa: S608
            "ORDER BY trade_date DESC, id DESC LIMIT $2 OFFSET $3",
            *args,
        )
    return TransactionPage(total=int(total or 0), items=[_tx_out(r) for r in rows])


@router.delete("/{pid}/transactions/{tx_id}", status_code=204)
async def remove_transaction(
    pid: int, tx_id: int, request: Request, user: Any = Depends(get_current_user)
) -> None:
    async with _pool(request).acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        if row["kind"] != "manual":
            raise HTTPException(status_code=409, detail="Synced portfolio is read-only")
        async with conn.transaction():
            try:
                found = await pdb.delete_transaction(conn, pid, tx_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Removing this transaction breaks the sequence: {exc}",
                ) from exc
        if not found:
            raise HTTPException(status_code=404, detail="Transaction not found")


# ── Holdings / allocation / snapshot ─────────────────────────────────────────


@router.get("/{pid}/holdings")
async def holdings(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> dict[str, Any]:
    async with _pool(request).acquire() as conn:
        await _own(conn, pid, _uid(user))
        valued = await _valued_holdings(request, conn, pid)
        scores: dict[str, dict[str, Any]] = {}
        if valued:
            rows = await conn.fetch(
                """
                SELECT e.symbol, s.composite, s.candidate, s.rank
                FROM screener_scores s JOIN equities e ON e.id = s.equity_id
                WHERE e.symbol = ANY($1)
                  AND s.score_date = (SELECT max(score_date) FROM screener_scores)
                """,
                [h.symbol for h in valued],
            )
            scores = {
                r["symbol"]: {
                    "composite": float(r["composite"]) if r["composite"] is not None else None,
                    "candidate": r["candidate"],
                    "rank": r["rank"],
                }
                for r in rows
            }
    return {
        "holdings": [{**h.model_dump(), "score": scores.get(h.symbol)} for h in valued],
        "disclaimer": DISCLAIMER,
    }


@router.get("/{pid}/allocation", response_model=AllocationOut)
async def allocation(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> AllocationOut:
    async with _pool(request).acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        valued = await _valued_holdings(request, conn, pid)
    values = {h.symbol: round((h.market_value or h.cost_basis) * 100) for h in valued}
    w = weights(values)
    by_sector: dict[str, float] = {}
    for h in valued:
        sector = h.sector or "Unknown"
        by_sector[sector] = by_sector.get(sector, 0.0) + (h.market_value or h.cost_basis)
    equity_total = sum(by_sector.values())
    cash = pdb.dollars(row["cash_cents"])
    total = equity_total + cash
    conc = concentration(values)
    return AllocationOut(
        by_sector=[
            SectorSlice(
                sector=s,
                weight_pct=round(v / equity_total * 100, 2) if equity_total else 0.0,
                value=round(v, 2),
            )
            for s, v in sorted(by_sector.items(), key=lambda kv: -kv[1])
        ],
        by_symbol=[
            SymbolSlice(
                symbol=h.symbol,
                weight_pct=round(w.get(h.symbol, 0) * 100, 2),
                value=round(h.market_value or h.cost_basis, 2),
            )
            for h in sorted(valued, key=lambda x: -(x.market_value or x.cost_basis))
        ],
        concentration=ConcentrationOut(
            **{k: v for k, v in conc.items() if k != "label"}, label=conc["label"]
        ),
        cash_pct=round(cash / total * 100, 2) if total else 0.0,
    )


@router.post("/{pid}/snapshot", response_model=SnapshotOut)
async def take_snapshot(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> SnapshotOut:
    today = datetime.now(UTC).date()
    async with _pool(request).acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        valued = await _valued_holdings(request, conn, pid)
        equity_cents = round(sum(h.market_value or h.cost_basis for h in valued) * 100)
        cash_cents = int(row["cash_cents"])
        realized_cents = round(sum(h.realized_pnl for h in valued) * 100)
        unrealized_cents = round(sum(h.unrealized_pnl or 0.0 for h in valued) * 100)
        flow = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM portfolio_transactions "
            "WHERE portfolio_id = $1 AND trade_date = $2 "
            "AND tx_type IN ('deposit', 'withdrawal')",
            pid,
            today,
        )
        detail = {
            h.symbol: {"qty": h.qty, "price": h.price, "value": h.market_value} for h in valued
        }
        await conn.execute(
            """
            INSERT INTO portfolio_snapshots (portfolio_id, snapshot_date,
                equity_value_cents, cash_cents, total_value_cents, net_flow_cents,
                realized_pnl_cents, unrealized_pnl_cents, holdings_count, detail)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (portfolio_id, snapshot_date) DO UPDATE SET
                equity_value_cents = EXCLUDED.equity_value_cents,
                cash_cents = EXCLUDED.cash_cents,
                total_value_cents = EXCLUDED.total_value_cents,
                net_flow_cents = EXCLUDED.net_flow_cents,
                realized_pnl_cents = EXCLUDED.realized_pnl_cents,
                unrealized_pnl_cents = EXCLUDED.unrealized_pnl_cents,
                holdings_count = EXCLUDED.holdings_count,
                detail = EXCLUDED.detail
            """,
            pid,
            today,
            equity_cents,
            cash_cents,
            equity_cents + cash_cents,
            int(flow or 0),
            realized_cents,
            unrealized_cents,
            len(valued),
            json.dumps(detail),
        )
    return SnapshotOut(
        portfolio_id=pid,
        snapshot_date=today,
        equity_value=equity_cents / 100,
        cash=cash_cents / 100,
        total_value=(equity_cents + cash_cents) / 100,
        net_flow=(flow or 0) / 100,
        realized_pnl=realized_cents / 100,
        unrealized_pnl=unrealized_cents / 100,
        holdings_count=len(valued),
    )


# ── Performance ───────────────────────────────────────────────────────────────

_RANGES = {"1m": 31, "3m": 92, "6m": 183, "1y": 366, "all": 10_000}


async def _beta(
    request: Request, conn: asyncpg.Connection, valued: list[HoldingOut]
) -> tuple[float | None, float]:
    """Portfolio beta vs SPY from 1y of stored daily closes; (beta, coverage)."""
    from app.screener.data import closes_map

    symbols = [h.symbol for h in valued]
    closes: dict[str, list[float]] = await closes_map(
        request.app.state.pool, [*symbols, "SPY"], days=260
    )
    spy = closes.get("SPY", [])
    if len(spy) < 61:
        return None, 0.0
    spy_ret = [spy[i] / spy[i - 1] - 1 for i in range(1, len(spy))]

    def beta_for(sym: str) -> float | None:
        c = closes.get(sym, [])
        if len(c) < 61:
            return None
        r = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
        n = min(len(r), len(spy_ret))
        if n < 60:
            return None
        rs, rm = r[-n:], spy_ret[-n:]
        mean_s, mean_m = sum(rs) / n, sum(rm) / n
        var_m = sum((x - mean_m) ** 2 for x in rm) / n
        if var_m == 0:
            return None
        cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(n)) / n
        return cov / var_m

    total_value = sum(h.market_value or h.cost_basis for h in valued)
    if total_value <= 0:
        return None, 0.0
    weighted = 0.0
    covered = 0.0
    for h in valued:
        b = beta_for(h.symbol)
        if b is None:
            continue
        w = (h.market_value or h.cost_basis) / total_value
        weighted += w * b
        covered += w
    if covered < 0.5:
        return None, round(covered, 2)
    return round(weighted / covered, 2), round(covered, 2)


@router.get("/{pid}/performance")
async def performance(
    pid: int,
    request: Request,
    range: str = Query("3m", pattern="^(1m|3m|6m|1y|all)$"),  # noqa: A002
    user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    from app.portfolio.math import chained_twr

    days = _RANGES[range]
    async with _pool(request).acquire() as conn:
        await _own(conn, pid, _uid(user))
        snaps = await conn.fetch(
            "SELECT * FROM portfolio_snapshots WHERE portfolio_id = $1 "
            "AND snapshot_date >= CURRENT_DATE - $2::int ORDER BY snapshot_date",
            pid,
            days,
        )
        contrib = await conn.fetchrow(
            """
            SELECT
              COALESCE(SUM(amount_cents) FILTER (WHERE tx_type IN ('deposit','withdrawal')), 0)
                AS net_contributions,
              COALESCE(SUM(amount_cents) FILTER (
                  WHERE tx_type = 'dividend'
                    AND trade_date >= CURRENT_DATE - $2::int), 0) AS income
            FROM portfolio_transactions WHERE portfolio_id = $1
            """,
            pid,
            days,
        )
        valued = await _valued_holdings(request, conn, pid)
        beta, beta_cov = await _beta(request, conn, valued)

    rows = [dict(s) for s in snaps]
    series = []
    index = 1.0
    for i, s in enumerate(rows):
        if i > 0 and rows[i - 1]["total_value_cents"] > 0:
            prev = rows[i - 1]["total_value_cents"]
            r = (s["total_value_cents"] - s["net_flow_cents"] - prev) / prev
            index *= 1.0 + r
        series.append(
            {
                "date": s["snapshot_date"].isoformat(),
                "total_value": s["total_value_cents"] / 100,
                "twr_index": round(index, 4),
            }
        )
    twr = chained_twr(rows)
    current_total = sum(h.market_value or h.cost_basis for h in valued) + (
        pdb.dollars(rows[-1]["cash_cents"]) if rows else 0.0
    )
    net_contrib = pdb.dollars(int(contrib["net_contributions"])) if contrib else 0.0
    simple = ((current_total - net_contrib) / net_contrib * 100) if net_contrib > 0 else None
    return {
        "series": series,
        "twr_pct": round(twr * 100, 2) if twr is not None else None,
        "simple_return_pct": round(simple, 2) if simple is not None else None,
        "simple_return_label": "vs money in",
        "realized_pnl": rows[-1]["realized_pnl_cents"] / 100 if rows else None,
        "unrealized_pnl": rows[-1]["unrealized_pnl_cents"] / 100 if rows else None,
        "income": pdb.dollars(int(contrib["income"])) if contrib else 0.0,
        "net_contributions": net_contrib,
        "beta": beta,
        "beta_coverage": beta_cov,
        "disclaimer": DISCLAIMER,
    }


# ── BUILD + INSIGHTS + AI commentary ─────────────────────────────────────────


async def _scores_for(conn: asyncpg.Connection, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    rows = await conn.fetch(
        """
        SELECT e.symbol, s.composite, s.candidate, s.rank
        FROM screener_scores s JOIN equities e ON e.id = s.equity_id
        WHERE e.symbol = ANY($1)
          AND s.score_date = (SELECT max(score_date) FROM screener_scores)
        """,
        symbols,
    )
    return {
        r["symbol"]: {
            "composite": float(r["composite"]) if r["composite"] is not None else None,
            "candidate": r["candidate"],
            "rank": r["rank"],
        }
        for r in rows
    }


def _cash_pct(row: Any, valued: list[HoldingOut]) -> float:
    cash = pdb.dollars(row["cash_cents"])
    total = sum(h.market_value or h.cost_basis for h in valued) + cash
    return round(cash / total * 100, 2) if total > 0 else 0.0


@router.get("/{pid}/health")
async def health(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> dict[str, Any]:
    from app.portfolio.health import diversification_score, run_health_checks

    async with _pool(request).acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        valued = await _valued_holdings(request, conn, pid)
        scores = await _scores_for(conn, [h.symbol for h in valued])
    dicts = [h.model_dump() for h in valued]
    checks: list[dict[str, Any]] = run_health_checks(dicts, _cash_pct(row, valued), scores)
    score: int = diversification_score(dicts)
    return {"diversification_score": score, "checks": checks, "disclaimer": DISCLAIMER}


@router.post("/{pid}/suggestions")
async def suggestions(
    pid: int,
    request: Request,
    body: dict[str, Any] | None = None,
    user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    from app.portfolio.health import suggest_allocation

    body = body or {}
    mode = str(body.get("mode", "score_weighted"))
    if mode not in ("equal_weight", "score_weighted"):
        raise HTTPException(status_code=422, detail="mode must be equal_weight|score_weighted")
    top_n = int(body.get("top_n", 5))
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        valued = await _valued_holdings(request, conn, pid)
        cands = await conn.fetch(
            """
            SELECT e.symbol, s.composite, s.candidate, s.price_cents
            FROM screener_scores s JOIN equities e ON e.id = s.equity_id
            WHERE s.score_date = (SELECT max(score_date) FROM screener_scores)
              AND s.candidate IN ('strong_buy', 'buy')
            ORDER BY s.rank ASC NULLS LAST LIMIT 40
            """
        )
    cash = float(body.get("cash", pdb.dollars(row["cash_cents"])))
    candidates = [
        {
            "symbol": c["symbol"],
            "composite": float(c["composite"]) if c["composite"] is not None else 0.0,
            "candidate": c["candidate"],
            "price": (c["price_cents"] or 0) / 100 if c["price_cents"] else None,
        }
        for c in cands
    ]
    result: list[dict[str, Any]] = suggest_allocation(
        cash, mode, [h.model_dump() for h in valued], candidates, top_n=top_n
    )
    return {
        "suggestions": result,
        "mode": mode,
        "cash_used": cash,
        "note": "Educational sizing illustration — not a recommendation.",
        "disclaimer": DISCLAIMER,
    }


@router.get("/{pid}/insights")
async def insights(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> dict[str, Any]:
    from app.portfolio.insights import build_insights

    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await _own(conn, pid, _uid(user))
        valued = await _valued_holdings(request, conn, pid)
    payload: dict[str, Any] = await build_insights(
        pool, [h.model_dump() for h in valued], _cash_pct(row, valued)
    )
    payload["disclaimer"] = DISCLAIMER
    return payload


async def _commentary_context(
    request: Request, pool: asyncpg.Pool, row: Any, pid: int, user: Any
) -> dict[str, Any]:
    from app.portfolio.commentary import build_context
    from app.portfolio.insights import build_insights

    async with pool.acquire() as conn:
        valued = await _valued_holdings(request, conn, pid)
    dicts = [h.model_dump() for h in valued]
    insights_payload: dict[str, Any] = await build_insights(pool, dicts, _cash_pct(row, valued))
    perf: dict[str, Any] | None = None
    try:
        perf = await performance(pid, request, range="3m", user=user)
    except Exception:  # noqa: BLE001 — commentary works without performance
        perf = None
    equity = sum(h.market_value or h.cost_basis for h in valued)
    portfolio_info = {
        "name": row["name"],
        "kind": row["kind"],
        "total_value": round(equity + pdb.dollars(row["cash_cents"]), 2),
        "cash": pdb.dollars(row["cash_cents"]),
    }
    ctx: dict[str, Any] = build_context(portfolio_info, dicts, insights_payload, perf)
    return ctx


@router.get("/{pid}/commentary")
async def get_commentary(
    pid: int, request: Request, user: Any = Depends(get_current_user)
) -> dict[str, Any]:
    from app.portfolio.commentary import get_cached

    pool = _pool(request)
    async with pool.acquire() as conn:
        await _own(conn, pid, _uid(user))
    cached: dict[str, Any] | None = await get_cached(pool, _uid(user), pid)
    if cached is None:
        raise HTTPException(status_code=404, detail="no commentary yet")
    return {**cached, "portfolio_id": pid, "cached": True, "disclaimer": DISCLAIMER}


@router.post("/{pid}/commentary")
async def post_commentary(
    pid: int,
    request: Request,
    body: dict[str, Any] | None = None,
    user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    from app.portfolio.commentary import CommentaryUnavailableError, generate

    force = bool((body or {}).get("force", False))
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await _own(conn, pid, _uid(user))
    ctx = await _commentary_context(request, pool, row, pid, user)
    try:
        result: dict[str, Any] = await generate(pool, _uid(user), pid, ctx, force=force)
    except CommentaryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {**result, "portfolio_id": pid, "disclaimer": DISCLAIMER}


# ── Alpaca paper sync ────────────────────────────────────────────────────────


@router.post("/sync/alpaca", response_model=SyncResult)
async def sync_alpaca(request: Request, user: Any = Depends(get_current_user)) -> SyncResult:
    try:
        result: dict[str, Any] = await sync_alpaca_paper(_pool(request), _uid(user))
    except AlpacaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SyncResult(
        portfolio_id=result["portfolio_id"],
        positions_synced=result["positions_synced"],
        cash=result["cash_cents"] / 100,
        as_of=datetime.now(UTC),
    )
