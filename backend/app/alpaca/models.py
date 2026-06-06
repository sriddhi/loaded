from pydantic import BaseModel


class AccountInfo(BaseModel):
    id: str
    status: str
    currency: str
    buying_power: float
    cash: float
    portfolio_value: float
    pattern_day_trader: bool
    trading_blocked: bool
    account_blocked: bool
    trade_suspended_by_user: bool
    is_paper: bool


class Position(BaseModel):
    symbol: str
    qty: float
    side: str
    avg_entry_price: float
    current_price: float | None
    market_value: float | None
    unrealized_pl: float | None
    unrealized_plpc: float | None
    change_today: float | None


class Order(BaseModel):
    id: str
    client_order_id: str
    symbol: str
    qty: float | None
    notional: float | None
    side: str
    type: str
    time_in_force: str
    limit_price: float | None
    stop_price: float | None
    status: str
    filled_qty: float | None
    filled_avg_price: float | None
    created_at: str
    filled_at: str | None


class OrderRequest(BaseModel):
    symbol: str
    qty: float | None = None
    notional: float | None = None
    side: str
    type: str = "market"
    time_in_force: str = "day"
    limit_price: float | None = None
    stop_price: float | None = None


class PortfolioSnapshot(BaseModel):
    timestamps: list[int]
    equity: list[float]
    profit_loss: list[float]
    profit_loss_pct: list[float]
    base_value: float
    timeframe: str


class MarketClock(BaseModel):
    timestamp: str
    is_open: bool
    next_open: str
    next_close: str
