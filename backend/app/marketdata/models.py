from pydantic import BaseModel

# ── Stock models ───────────────────────────────────────────────────────────────


class Bar(BaseModel):
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None


class Quote(BaseModel):
    symbol: str
    timestamp: str
    ask_price: float | None = None
    ask_size: float | None = None
    bid_price: float | None = None
    bid_size: float | None = None


class Trade(BaseModel):
    symbol: str
    timestamp: str
    price: float
    size: float
    exchange: str | None = None


class Snapshot(BaseModel):
    symbol: str
    latest_trade: Trade | None = None
    latest_quote: Quote | None = None
    minute_bar: Bar | None = None
    daily_bar: Bar | None = None
    prev_daily_bar: Bar | None = None


class MarketMover(BaseModel):
    symbol: str
    percent_change: float
    change: float
    price: float


class MarketMovers(BaseModel):
    gainers: list[MarketMover]
    losers: list[MarketMover]


class ActiveStock(BaseModel):
    symbol: str
    volume: float | None = None
    trade_count: int | None = None
    price: float | None = None


class NewsItem(BaseModel):
    id: int
    headline: str
    summary: str | None = None
    url: str | None = None
    source: str | None = None
    author: str | None = None
    created_at: str
    updated_at: str
    symbols: list[str]


# ── Options models ─────────────────────────────────────────────────────────────


class OptionGreeks(BaseModel):
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None


class OptionContract(BaseModel):
    symbol: str
    underlying_symbol: str
    type: str  # call | put
    strike_price: float
    expiration_date: str  # YYYY-MM-DD
    style: str | None = None  # american | european
    status: str | None = None  # active | inactive
    size: float | None = None  # contract multiplier (usually 100)


class OptionQuote(BaseModel):
    symbol: str
    timestamp: str | None = None
    bid_price: float | None = None
    bid_size: float | None = None
    ask_price: float | None = None
    ask_size: float | None = None


class OptionTrade(BaseModel):
    symbol: str
    timestamp: str | None = None
    price: float | None = None
    size: float | None = None


class OptionSnapshot(BaseModel):
    symbol: str
    latest_quote: OptionQuote | None = None
    latest_trade: OptionTrade | None = None
    implied_volatility: float | None = None
    greeks: OptionGreeks | None = None
