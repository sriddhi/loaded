"""
Alpaca trading API endpoints.

All endpoints support both paper and live accounts — controlled by ALPACA_PAPER_TRADE env var.
"""

import logging
from typing import Any

from app.alpaca.client import alpaca_configured, get_trading_client, paper_trading_enabled
from app.alpaca.models import (
    AccountInfo,
    MarketClock,
    Order,
    OrderRequest,
    PortfolioSnapshot,
    Position,
)
from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/alpaca", tags=["alpaca"])

_NOT_CONFIGURED = HTTPException(status_code=503, detail="Alpaca credentials not configured")


def _get_client() -> Any:
    """Get trading client or raise 503."""
    if not alpaca_configured():
        raise _NOT_CONFIGURED
    try:
        return get_trading_client()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _api_error(e: Exception, not_found: bool = False) -> HTTPException:
    """Convert Alpaca SDK errors to appropriate HTTP errors."""
    msg = str(e)
    status = 404 if not_found else 502
    return HTTPException(status_code=status, detail=msg)


# ── Account ───────────────────────────────────────────────────────────────────


@router.get("/account", response_model=AccountInfo)
async def get_account() -> AccountInfo:
    client = _get_client()
    try:
        acct = client.get_account()
    except Exception as e:
        raise _api_error(e) from e
    return AccountInfo(
        id=str(acct.id),
        status=str(acct.status),
        currency=str(acct.currency),
        buying_power=float(acct.buying_power),
        cash=float(acct.cash),
        portfolio_value=float(acct.portfolio_value),
        pattern_day_trader=bool(acct.pattern_day_trader),
        trading_blocked=bool(acct.trading_blocked),
        account_blocked=bool(acct.account_blocked),
        trade_suspended_by_user=bool(acct.trade_suspended_by_user),
        is_paper=paper_trading_enabled(),
    )


@router.get("/account/clock", response_model=MarketClock)
async def get_clock() -> MarketClock:
    client = _get_client()
    try:
        clock = client.get_clock()
    except Exception as e:
        raise _api_error(e) from e
    return MarketClock(
        timestamp=str(clock.timestamp),
        is_open=bool(clock.is_open),
        next_open=str(clock.next_open),
        next_close=str(clock.next_close),
    )


# ── Positions ─────────────────────────────────────────────────────────────────


def _to_position(p: Any) -> Position:
    return Position(
        symbol=str(p.symbol),
        qty=float(p.qty),
        side=str(p.side),
        avg_entry_price=float(p.avg_entry_price),
        current_price=float(p.current_price) if p.current_price is not None else None,
        market_value=float(p.market_value) if p.market_value is not None else None,
        unrealized_pl=float(p.unrealized_pl) if p.unrealized_pl is not None else None,
        unrealized_plpc=float(p.unrealized_plpc) if p.unrealized_plpc is not None else None,
        change_today=float(p.change_today) if p.change_today is not None else None,
    )


@router.get("/positions", response_model=list[Position])
async def get_positions() -> list[Position]:
    client = _get_client()
    try:
        positions = client.get_all_positions()
    except Exception as e:
        raise _api_error(e) from e
    return [_to_position(p) for p in positions]


@router.get("/positions/{symbol}", response_model=Position)
async def get_position(symbol: str) -> Position:
    client = _get_client()
    try:
        p = client.get_open_position(symbol)
    except Exception as e:
        raise _api_error(e, not_found=True) from e
    return _to_position(p)


@router.delete("/positions/{symbol}")
async def close_position(symbol: str) -> dict[str, Any]:
    client = _get_client()
    try:
        order = client.close_position(symbol)
    except Exception as e:
        raise _api_error(e, not_found=True) from e
    return {"message": "Position closed", "order": _to_order(order).model_dump()}


# ── Orders ────────────────────────────────────────────────────────────────────


def _to_order(o: Any) -> Order:
    return Order(
        id=str(o.id),
        client_order_id=str(o.client_order_id),
        symbol=str(o.symbol),
        qty=float(o.qty) if o.qty is not None else None,
        notional=float(o.notional) if o.notional is not None else None,
        side=str(o.side),
        type=str(o.order_type) if hasattr(o, "order_type") else str(o.type),
        time_in_force=str(o.time_in_force),
        limit_price=float(o.limit_price) if o.limit_price is not None else None,
        stop_price=float(o.stop_price) if o.stop_price is not None else None,
        status=str(o.status),
        filled_qty=float(o.filled_qty) if o.filled_qty is not None else None,
        filled_avg_price=(float(o.filled_avg_price) if o.filled_avg_price is not None else None),
        created_at=str(o.created_at),
        filled_at=str(o.filled_at) if o.filled_at is not None else None,
    )


@router.get("/orders", response_model=list[Order])
async def get_orders(
    status: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[Order]:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    status_map = {
        "open": QueryOrderStatus.OPEN,
        "closed": QueryOrderStatus.CLOSED,
        "all": QueryOrderStatus.ALL,
    }
    query_status = status_map.get(status, QueryOrderStatus.OPEN)
    client = _get_client()
    try:
        orders = client.get_orders(filter=GetOrdersRequest(status=query_status, limit=limit))
    except Exception as e:
        raise _api_error(e) from e
    return [_to_order(o) for o in orders]


@router.post("/orders", response_model=Order)
async def place_order(body: OrderRequest) -> Order:
    if body.qty is not None and body.notional is not None:
        raise HTTPException(status_code=422, detail="Provide either qty or notional, not both")
    if body.qty is None and body.notional is None:
        raise HTTPException(status_code=422, detail="Either qty or notional is required")

    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import (
        LimitOrderRequest,
        MarketOrderRequest,
        StopLimitOrderRequest,
        StopOrderRequest,
    )

    side = OrderSide.BUY if body.side.lower() == "buy" else OrderSide.SELL
    tif_map = {
        "day": TimeInForce.DAY,
        "gtc": TimeInForce.GTC,
        "ioc": TimeInForce.IOC,
        "fok": TimeInForce.FOK,
    }
    tif = tif_map.get(body.time_in_force.lower(), TimeInForce.DAY)

    order_type = body.type.lower()
    req: Any
    try:
        if order_type == "market":
            req = MarketOrderRequest(
                symbol=body.symbol,
                qty=body.qty,
                notional=body.notional,
                side=side,
                time_in_force=tif,
            )
        elif order_type == "limit":
            req = LimitOrderRequest(
                symbol=body.symbol,
                qty=body.qty,
                notional=body.notional,
                side=side,
                time_in_force=tif,
                limit_price=body.limit_price,
            )
        elif order_type == "stop":
            req = StopOrderRequest(
                symbol=body.symbol,
                qty=body.qty,
                side=side,
                time_in_force=tif,
                stop_price=body.stop_price,
            )
        elif order_type == "stop_limit":
            req = StopLimitOrderRequest(
                symbol=body.symbol,
                qty=body.qty,
                side=side,
                time_in_force=tif,
                limit_price=body.limit_price,
                stop_price=body.stop_price,
            )
        else:
            raise HTTPException(status_code=422, detail=f"Unknown order type: {body.type}")

        client = _get_client()
        order = client.submit_order(req)
    except HTTPException:
        raise
    except Exception as e:
        raise _api_error(e) from e

    return _to_order(order)


@router.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str) -> Order:
    client = _get_client()
    try:
        order = client.get_order_by_id(order_id)
    except Exception as e:
        raise _api_error(e, not_found=True) from e
    return _to_order(order)


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str) -> dict[str, str]:
    client = _get_client()
    try:
        client.cancel_order_by_id(order_id)
    except Exception as e:
        raise _api_error(e, not_found=True) from e
    return {"message": "Order cancelled"}


# ── Portfolio History ─────────────────────────────────────────────────────────


@router.get("/portfolio/history", response_model=PortfolioSnapshot)
async def get_portfolio_history(
    period: str = Query(default="1M"),
    timeframe: str = Query(default="1D"),
) -> PortfolioSnapshot:
    from alpaca.trading.requests import GetPortfolioHistoryRequest

    # timeframe is a plain string: 1Min | 5Min | 15Min | 1H | 1D
    valid_timeframes = {"1Min", "5Min", "15Min", "1H", "1D"}
    tf = timeframe if timeframe in valid_timeframes else "1D"

    client = _get_client()
    try:
        history = client.get_portfolio_history(
            filter=GetPortfolioHistoryRequest(period=period, timeframe=tf)
        )
    except Exception as e:
        raise _api_error(e) from e

    return PortfolioSnapshot(
        timestamps=[int(t) for t in (history.timestamp or [])],
        equity=[float(v) for v in (history.equity or [])],
        profit_loss=[float(v) for v in (history.profit_loss or [])],
        profit_loss_pct=[float(v) for v in (history.profit_loss_pct or [])],
        base_value=float(history.base_value) if history.base_value is not None else 0.0,
        timeframe=str(history.timeframe) if history.timeframe is not None else timeframe,
    )
