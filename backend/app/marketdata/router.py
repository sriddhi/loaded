"""
Alpaca market data endpoints — stocks, options, and news.

No account param needed here: market data uses a separate client that works
with or without credentials (authenticated = SIP/OPRA feeds, unauthenticated = delayed/indicative).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.marketdata.client import (
    _ALPACA_DATA_AVAILABLE,
    get_news_client,
    get_option_client,
    get_screener_client,
    get_stock_client,
)
from app.marketdata.models import (
    ActiveStock,
    Bar,
    MarketMover,
    MarketMovers,
    NewsItem,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionSnapshot,
    OptionTrade,
    Quote,
    Snapshot,
    Trade,
)
from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/marketdata", tags=["marketdata"])


# ── Helpers ────────────────────────────────────────────────────────────────────


def _require_data() -> None:
    if not _ALPACA_DATA_AVAILABLE:
        raise HTTPException(status_code=503, detail="alpaca-py package is not installed")


def _data_error(e: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=str(e))


def _timeframe(tf_str: str) -> Any:
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    mapping: dict[str, Any] = {
        "1Min": TimeFrame.Minute,
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame.Hour,
        "1Day": TimeFrame.Day,
        "1Week": TimeFrame.Week,
        "1Month": TimeFrame.Month,
    }
    return mapping.get(tf_str, TimeFrame.Day)


def _to_bar(symbol: str, b: Any) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=str(b.timestamp),
        open=float(b.open),
        high=float(b.high),
        low=float(b.low),
        close=float(b.close),
        volume=float(b.volume),
        vwap=float(b.vwap) if getattr(b, "vwap", None) is not None else None,
        trade_count=int(b.trade_count) if getattr(b, "trade_count", None) is not None else None,
    )


def _to_quote(symbol: str, q: Any) -> Quote:
    return Quote(
        symbol=symbol,
        timestamp=str(q.timestamp),
        ask_price=float(q.ask_price) if getattr(q, "ask_price", None) is not None else None,
        ask_size=float(q.ask_size) if getattr(q, "ask_size", None) is not None else None,
        bid_price=float(q.bid_price) if getattr(q, "bid_price", None) is not None else None,
        bid_size=float(q.bid_size) if getattr(q, "bid_size", None) is not None else None,
    )


def _to_trade(symbol: str, t: Any) -> Trade:
    return Trade(
        symbol=symbol,
        timestamp=str(t.timestamp),
        price=float(t.price),
        size=float(t.size),
        exchange=str(t.exchange) if getattr(t, "exchange", None) is not None else None,
    )


def _to_snapshot(symbol: str, s: Any) -> Snapshot:
    lt = getattr(s, "latest_trade", None)
    lq = getattr(s, "latest_quote", None)
    mb = getattr(s, "minute_bar", None)
    db = getattr(s, "daily_bar", None)
    pb = getattr(s, "previous_daily_bar", None) or getattr(s, "prev_daily_bar", None)
    return Snapshot(
        symbol=symbol,
        latest_trade=_to_trade(symbol, lt) if lt is not None else None,
        latest_quote=_to_quote(symbol, lq) if lq is not None else None,
        minute_bar=_to_bar(symbol, mb) if mb is not None else None,
        daily_bar=_to_bar(symbol, db) if db is not None else None,
        prev_daily_bar=_to_bar(symbol, pb) if pb is not None else None,
    )


def _to_option_snapshot(symbol: str, s: Any) -> OptionSnapshot:
    lq = getattr(s, "latest_quote", None)
    lt = getattr(s, "latest_trade", None)
    gr = getattr(s, "greeks", None)
    iv = getattr(s, "implied_volatility", None)
    return OptionSnapshot(
        symbol=symbol,
        latest_quote=OptionQuote(
            symbol=symbol,
            timestamp=str(lq.timestamp) if getattr(lq, "timestamp", None) is not None else None,
            bid_price=float(lq.bid_price) if getattr(lq, "bid_price", None) is not None else None,
            bid_size=float(lq.bid_size) if getattr(lq, "bid_size", None) is not None else None,
            ask_price=float(lq.ask_price) if getattr(lq, "ask_price", None) is not None else None,
            ask_size=float(lq.ask_size) if getattr(lq, "ask_size", None) is not None else None,
        )
        if lq is not None
        else None,
        latest_trade=OptionTrade(
            symbol=symbol,
            timestamp=str(lt.timestamp) if getattr(lt, "timestamp", None) is not None else None,
            price=float(lt.price) if getattr(lt, "price", None) is not None else None,
            size=float(lt.size) if getattr(lt, "size", None) is not None else None,
        )
        if lt is not None
        else None,
        implied_volatility=float(iv) if iv is not None else None,
        greeks=OptionGreeks(
            delta=float(gr.delta) if getattr(gr, "delta", None) is not None else None,
            gamma=float(gr.gamma) if getattr(gr, "gamma", None) is not None else None,
            theta=float(gr.theta) if getattr(gr, "theta", None) is not None else None,
            vega=float(gr.vega) if getattr(gr, "vega", None) is not None else None,
            rho=float(gr.rho) if getattr(gr, "rho", None) is not None else None,
        )
        if gr is not None
        else None,
    )


# ── Stock endpoints ────────────────────────────────────────────────────────────
# NOTE: static routes (movers, active, news) MUST be before /{symbol} routes.


@router.get("/stocks/movers", response_model=MarketMovers)
async def get_movers(top: int = Query(default=10, ge=1, le=50)) -> MarketMovers:
    _require_data()
    from alpaca.data.enums import MarketType
    from alpaca.data.requests import MarketMoversRequest

    client = get_screener_client()
    try:
        result = client.get_market_movers(
            MarketMoversRequest(market_type=MarketType.STOCKS, top=top)
        )
    except Exception as e:
        raise _data_error(e) from e

    def _mover(m: Any) -> MarketMover:
        return MarketMover(
            symbol=str(m.symbol),
            percent_change=float(m.percent_change),
            change=float(m.change),
            price=float(m.price),
        )

    return MarketMovers(
        gainers=[_mover(m) for m in (getattr(result, "gainers", None) or [])],
        losers=[_mover(m) for m in (getattr(result, "losers", None) or [])],
    )


@router.get("/stocks/active", response_model=list[ActiveStock])
async def get_active(
    by: str = Query(default="volume", pattern="^(volume|trades)$"),
    top: int = Query(default=10, ge=1, le=100),
) -> list[ActiveStock]:
    _require_data()
    from alpaca.data.enums import MostActivesBy
    from alpaca.data.requests import MostActivesRequest

    by_enum = MostActivesBy.TRADES if by == "trades" else MostActivesBy.VOLUME
    client = get_screener_client()
    try:
        result = client.get_most_actives(MostActivesRequest(top=top, by=by_enum))
    except Exception as e:
        raise _data_error(e) from e

    items = getattr(result, "most_actives", None) or []
    return [
        ActiveStock(
            symbol=str(a.symbol),
            volume=float(a.volume) if getattr(a, "volume", None) is not None else None,
            trade_count=int(a.trade_count) if getattr(a, "trade_count", None) is not None else None,
            price=float(a.price) if getattr(a, "price", None) is not None else None,
        )
        for a in items
    ]


@router.get("/stocks/news", response_model=list[NewsItem])
async def get_news(
    symbols: str | None = Query(default=None, description="Comma-separated symbols e.g. AAPL,TSLA"),
    limit: int = Query(default=10, ge=1, le=50),
    start: str | None = Query(default=None, description="Start date YYYY-MM-DD"),
    end: str | None = Query(default=None, description="End date YYYY-MM-DD"),
) -> list[NewsItem]:
    _require_data()
    from alpaca.data.requests import NewsRequest

    # NewsRequest.symbols expects a comma-separated string, not a list
    # NewsRequest.symbols expects a comma-separated string, not a list
    symbols_str = ",".join(s.strip().upper() for s in symbols.split(",")) if symbols else None
    client = get_news_client()
    try:
        kwargs: dict[str, Any] = {"limit": limit}
        if symbols_str:
            kwargs["symbols"] = symbols_str
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end
        raw: Any = client.get_news(NewsRequest(**kwargs))
    except Exception as e:
        raise _data_error(e) from e

    items: list[Any] = list(raw) if not isinstance(raw, list) else raw
    return [
        NewsItem(
            id=int(n.id),
            headline=str(n.headline),
            summary=str(n.summary) if getattr(n, "summary", None) is not None else None,
            url=str(n.url) if getattr(n, "url", None) is not None else None,
            source=str(n.source) if getattr(n, "source", None) is not None else None,
            author=str(n.author) if getattr(n, "author", None) is not None else None,
            created_at=str(n.created_at),
            updated_at=str(n.updated_at),
            symbols=[str(sym) for sym in (getattr(n, "symbols", None) or [])],
        )
        for n in items
    ]


@router.get("/stocks/{symbol}/snapshot", response_model=Snapshot)
async def get_snapshot(symbol: str) -> Snapshot:
    _require_data()
    from alpaca.data.requests import StockSnapshotRequest

    sym = symbol.upper()
    client = get_stock_client()
    try:
        result = client.get_stock_snapshot(StockSnapshotRequest(symbol_or_symbols=[sym]))
    except Exception as e:
        raise _data_error(e) from e

    if sym not in result:
        raise HTTPException(status_code=404, detail=f"Symbol {sym} not found")
    return _to_snapshot(sym, result[sym])


@router.get("/stocks/{symbol}/bars", response_model=list[Bar])
async def get_bars(
    symbol: str,
    timeframe: str = Query(default="1Day"),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=1000, ge=1, le=10000),
) -> list[Bar]:
    _require_data()
    from alpaca.data.requests import StockBarsRequest

    sym = symbol.upper()
    tf = _timeframe(timeframe)
    start = datetime.now(UTC) - timedelta(days=days)
    client = get_stock_client()
    try:
        result = client.get_stock_bars(
            StockBarsRequest(symbol_or_symbols=[sym], timeframe=tf, start=start, limit=limit)
        )
    except Exception as e:
        raise _data_error(e) from e

    bars = result.get(sym, []) if hasattr(result, "get") else result.data.get(sym, [])
    return [_to_bar(sym, b) for b in bars]


@router.get("/stocks/{symbol}/quote", response_model=Quote)
async def get_quote(symbol: str) -> Quote:
    _require_data()
    from alpaca.data.requests import StockLatestQuoteRequest

    sym = symbol.upper()
    client = get_stock_client()
    try:
        result = client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[sym]))
    except Exception as e:
        raise _data_error(e) from e

    if sym not in result:
        raise HTTPException(status_code=404, detail=f"Symbol {sym} not found")
    return _to_quote(sym, result[sym])


@router.get("/stocks/{symbol}/trade", response_model=Trade)
async def get_trade(symbol: str) -> Trade:
    _require_data()
    from alpaca.data.requests import StockLatestTradeRequest

    sym = symbol.upper()
    client = get_stock_client()
    try:
        result = client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=[sym]))
    except Exception as e:
        raise _data_error(e) from e

    if sym not in result:
        raise HTTPException(status_code=404, detail=f"Symbol {sym} not found")
    return _to_trade(sym, result[sym])


# ── Options endpoints ──────────────────────────────────────────────────────────


@router.get("/options/chain/{underlying_symbol}", response_model=list[OptionSnapshot])
async def get_option_chain(
    underlying_symbol: str,
    type: str | None = Query(default=None, pattern="^(call|put)$"),
    expiration: str | None = Query(default=None, description="Exact expiry YYYY-MM-DD"),
    expiry_gte: str | None = Query(default=None),
    expiry_lte: str | None = Query(default=None),
    strike_gte: float | None = Query(default=None),
    strike_lte: float | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[OptionSnapshot]:
    _require_data()
    from alpaca.data.requests import OptionChainRequest

    sym = underlying_symbol.upper()
    kwargs: dict[str, Any] = {"underlying_symbol": sym, "limit": limit}
    if type:
        kwargs["type"] = type
    if expiration:
        kwargs["expiration_date"] = expiration
    if expiry_gte:
        kwargs["expiration_date_gte"] = expiry_gte
    if expiry_lte:
        kwargs["expiration_date_lte"] = expiry_lte
    if strike_gte is not None:
        kwargs["strike_price_gte"] = strike_gte
    if strike_lte is not None:
        kwargs["strike_price_lte"] = strike_lte

    client = get_option_client()
    try:
        result = client.get_option_chain(OptionChainRequest(**kwargs))
    except Exception as e:
        raise _data_error(e) from e

    return [_to_option_snapshot(sym, snap) for sym, snap in result.items()]


@router.get("/options/contracts", response_model=list[OptionContract])
async def get_option_contracts(
    underlying: str | None = Query(default=None),
    type: str | None = Query(default=None, pattern="^(call|put)$"),
    expiration: str | None = Query(default=None, description="Exact expiry YYYY-MM-DD"),
    expiry_gte: str | None = Query(default=None),
    expiry_lte: str | None = Query(default=None),
    strike_gte: float | None = Query(default=None),
    strike_lte: float | None = Query(default=None),
    status: str = Query(default="active", pattern="^(active|inactive)$"),
    limit: int = Query(default=100, ge=1, le=10000),
) -> list[OptionContract]:
    from alpaca.trading.requests import GetOptionContractsRequest
    from app.alpaca.client import get_trading_client

    kwargs: dict[str, Any] = {"status": status, "limit": limit}
    if underlying:
        kwargs["underlying_symbols"] = [underlying.upper()]
    if type:
        kwargs["type"] = type
    if expiration:
        kwargs["expiration_date"] = expiration
    if expiry_gte:
        kwargs["expiration_date_gte"] = expiry_gte
    if expiry_lte:
        kwargs["expiration_date_lte"] = expiry_lte
    if strike_gte is not None:
        kwargs["strike_price_gte"] = strike_gte
    if strike_lte is not None:
        kwargs["strike_price_lte"] = strike_lte

    try:
        trading_client = get_trading_client(paper=True)
        result = trading_client.get_option_contracts(GetOptionContractsRequest(**kwargs))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise _data_error(e) from e

    contracts = getattr(result, "option_contracts", None) or []
    return [
        OptionContract(
            symbol=str(c.symbol),
            underlying_symbol=str(c.underlying_symbol),
            type=str(c.type).lower().replace("optiontype.", ""),
            strike_price=float(c.strike_price),
            expiration_date=str(c.expiration_date),
            style=str(c.style).lower().replace("exercisestyle.", "")
            if getattr(c, "style", None) is not None
            else None,
            status=str(c.status).lower().replace("assetstatus.", "")
            if getattr(c, "status", None) is not None
            else None,
            size=float(c.size) if getattr(c, "size", None) is not None else None,
        )
        for c in contracts
    ]


@router.get("/options/snapshot", response_model=list[OptionSnapshot])
async def get_option_snapshot(
    symbols: str = Query(description="Comma-separated OCC contract symbols"),
) -> list[OptionSnapshot]:
    _require_data()
    from alpaca.data.requests import OptionSnapshotRequest

    syms = [s.strip().upper() for s in symbols.split(",")]
    client = get_option_client()
    try:
        result = client.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=syms))
    except Exception as e:
        raise _data_error(e) from e

    return [_to_option_snapshot(sym, snap) for sym, snap in result.items()]


@router.get("/options/quote", response_model=list[OptionQuote])
async def get_option_quote(
    symbols: str = Query(description="Comma-separated OCC contract symbols"),
) -> list[OptionQuote]:
    _require_data()
    from alpaca.data.requests import OptionLatestQuoteRequest

    syms = [s.strip().upper() for s in symbols.split(",")]
    client = get_option_client()
    try:
        result = client.get_option_latest_quote(OptionLatestQuoteRequest(symbol_or_symbols=syms))
    except Exception as e:
        raise _data_error(e) from e

    return [
        OptionQuote(
            symbol=sym,
            timestamp=str(q.timestamp) if getattr(q, "timestamp", None) is not None else None,
            bid_price=float(q.bid_price) if getattr(q, "bid_price", None) is not None else None,
            bid_size=float(q.bid_size) if getattr(q, "bid_size", None) is not None else None,
            ask_price=float(q.ask_price) if getattr(q, "ask_price", None) is not None else None,
            ask_size=float(q.ask_size) if getattr(q, "ask_size", None) is not None else None,
        )
        for sym, q in result.items()
    ]
