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
    return {"holdings": [h.model_dump() for h in valued], "disclaimer": DISCLAIMER}


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
