"""Pydantic models for the portfolio module. Dollars at the boundary, cents in DB."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = "Heuristic, educational — not financial advice."

TxType = Literal["buy", "sell", "dividend", "deposit", "withdrawal"]


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PortfolioPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None


class TransactionCreate(BaseModel):
    tx_type: TxType
    symbol: str | None = Field(default=None, max_length=12)
    qty: float | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, gt=0)  # dollars per share
    amount: float | None = Field(default=None, gt=0)  # dollars, cash-only types
    fees: float = Field(default=0.0, ge=0)
    trade_date: date
    note: str | None = Field(default=None, max_length=300)


class TransactionOut(BaseModel):
    id: int
    portfolio_id: int
    symbol: str | None
    tx_type: str
    qty: float | None
    price: float | None
    amount: float
    fees: float
    trade_date: date
    note: str | None
    source: str
    created_at: datetime


class HoldingOut(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    qty: float
    avg_cost: float
    cost_basis: float
    price: float | None = None
    price_stale: bool = False
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pct: float | None = None
    weight_pct: float | None = None
    realized_pnl: float
    first_acquired: date | None = None


class PortfolioOut(BaseModel):
    id: int
    name: str
    kind: str
    cash: float
    is_active: bool
    last_synced_at: datetime | None
    created_at: datetime
    holdings_count: int = 0
    equity_value: float | None = None
    total_value: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None


class PortfolioDetail(PortfolioOut):
    holdings: list[HoldingOut] = []
    disclaimer: str = DISCLAIMER


class TransactionPage(BaseModel):
    total: int
    items: list[TransactionOut]


class TransactionResult(BaseModel):
    transaction: TransactionOut
    holding: HoldingOut | None = None


class SectorSlice(BaseModel):
    sector: str
    weight_pct: float
    value: float


class SymbolSlice(BaseModel):
    symbol: str
    weight_pct: float
    value: float


class ConcentrationOut(BaseModel):
    top1_pct: float
    top5_pct: float
    hhi: float
    label: str


class AllocationOut(BaseModel):
    by_sector: list[SectorSlice]
    by_symbol: list[SymbolSlice]
    concentration: ConcentrationOut
    cash_pct: float
    disclaimer: str = DISCLAIMER


class SyncResult(BaseModel):
    portfolio_id: int
    positions_synced: int
    cash: float
    as_of: datetime


class SnapshotOut(BaseModel):
    portfolio_id: int
    snapshot_date: date
    equity_value: float
    cash: float
    total_value: float
    net_flow: float
    realized_pnl: float
    unrealized_pnl: float
    holdings_count: int
