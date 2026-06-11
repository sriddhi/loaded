"""
SPY 0-3 DTE options paper-trading job (time-boxed experiment).

Every minute, derive a short-term SPY direction from 1-minute momentum and, while
the market is open, BUY one near-ATM 0-3 DTE option (CALL on up, PUT on down) on
the Alpaca PAPER account. Each position is held briefly, then closed; realized
P&L decides whether the decision was "right" or "wrong". A running report
(right vs wrong + total upside) is written to a JSON file.

SAFETY — hard guarantees:
- PAPER ONLY: every client is `TradingClient(paper=True)`; the job aborts unless
  paper credentials are configured. It never touches a real-money account.
- LONG OPTIONS ONLY (buy calls/puts) → max loss is the premium paid; no selling
  /writing, no naked risk.
- Time-boxed: stops at OPT_END_PT (default 13:15 America/Los_Angeles) and only
  trades while the market clock is open. 1 contract/trade, capped concurrency.

Run (inside the backend container, detached):
    python -m app.options_paper_job
Report: $OPTIONS_REPORT_PATH (default /app/options_report.json).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("options_paper_job")

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")

REPORT_PATH = os.getenv("OPTIONS_REPORT_PATH", "/app/options_report.json")
HOLD_MIN = int(os.getenv("OPT_HOLD_MIN", "5"))
MAX_OPEN = int(os.getenv("OPT_MAX_OPEN", "5"))
MOM_THRESHOLD = float(os.getenv("OPT_MOM_THRESHOLD", "0.0006"))  # 5-min return to act
END_PT = os.getenv("OPT_END_PT", "13:15")  # America/Los_Angeles HH:MM
QTY = 1


def _clients() -> tuple[Any, Any]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    key = os.getenv("ALPACA_PAPER_API_KEY")
    sec = os.getenv("ALPACA_PAPER_SECRET_KEY")
    if not key or not sec:
        raise SystemExit("Refusing to run: Alpaca PAPER credentials are not configured.")
    return TradingClient(key, sec, paper=True), StockHistoricalDataClient(key, sec)


def spy_direction(stock_client: Any) -> tuple[str, float]:
    """('CALL'|'PUT'|'SKIP', spy_price) from ~5-minute SPY momentum."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    req = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Minute, limit=15)
    data = stock_client.get_stock_bars(req).data.get("SPY", [])
    closes = [float(b.close) for b in data]
    if len(closes) < 6:
        return "SKIP", (closes[-1] if closes else 0.0)
    price, ref = closes[-1], closes[-6]
    ret = (price - ref) / ref if ref else 0.0
    if ret >= MOM_THRESHOLD:
        return "CALL", price
    if ret <= -MOM_THRESHOLD:
        return "PUT", price
    return "SKIP", price


def pick_contract(tc: Any, side: str, price: float) -> Any | None:
    """Nearest-ATM 0-3 DTE contract of the requested type (prefer nearest expiry)."""
    from alpaca.trading.enums import AssetStatus, ContractType
    from alpaca.trading.requests import GetOptionContractsRequest

    today = datetime.now(ET).date()
    req = GetOptionContractsRequest(
        underlying_symbols=["SPY"],
        status=AssetStatus.ACTIVE,
        type=ContractType.CALL if side == "CALL" else ContractType.PUT,
        expiration_date_gte=today,
        expiration_date_lte=today + timedelta(days=3),
        strike_price_gte=str(round(price - 10)),
        strike_price_lte=str(round(price + 10)),
        limit=100,
    )
    cons = tc.get_option_contracts(req).option_contracts or []
    if not cons:
        return None
    cons.sort(key=lambda c: (str(c.expiration_date), abs(float(c.strike_price) - price)))
    return cons[0]


def _order(tc: Any, symbol: str, buy: bool) -> Any:
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    return tc.submit_order(
        MarketOrderRequest(
            symbol=symbol,
            qty=QTY,
            side=OrderSide.BUY if buy else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
    )


def _filled_price(tc: Any, order_id: Any, timeout: int = 20) -> float | None:
    end = time.time() + timeout
    while time.time() < end:
        o = tc.get_order_by_id(order_id)
        status_raw = getattr(o, "status", None)
        status = (getattr(status_raw, "value", None) or str(status_raw)).lower()
        if o.filled_avg_price and status in ("filled", "partially_filled"):
            return float(o.filled_avg_price)
        time.sleep(1)
    return None


def _write_report(
    closed: list[dict[str, Any]], open_trades: list[dict[str, Any]], start: datetime
) -> None:
    right = sum(1 for t in closed if t["right"])
    wrong = len(closed) - right
    total_upside = round(sum(t["pnl"] for t in closed), 2)
    report = {
        "title": "SPY 0-3 DTE options — paper decision report",
        "account": "ALPACA PAPER (long options only)",
        "started_pt": start.astimezone(PT).strftime("%Y-%m-%d %H:%M %Z"),
        "ends_pt": END_PT + " PT",
        "updated": datetime.now(UTC).isoformat(),
        "decisions": len(closed),
        "right": right,
        "wrong": wrong,
        "win_rate_pct": round(right / len(closed) * 100, 1) if closed else None,
        "total_upside_usd": total_upside,
        "avg_per_trade_usd": round(total_upside / len(closed), 2) if closed else None,
        "open_now": len(open_trades),
        "trades": closed[-50:],
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)


def main() -> None:
    tc, sd = _clients()
    acct = tc.get_account()
    log.info(
        "PAPER account %s · options level %s · buying power %s",
        getattr(acct, "status", "?"),
        getattr(acct, "options_trading_level", "?"),
        getattr(acct, "buying_power", "?"),
    )

    now_pt = datetime.now(PT)
    hh, mm = (int(x) for x in END_PT.split(":"))
    end_pt = now_pt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end_pt <= now_pt:
        end_pt = end_pt + timedelta(days=1)
    log.info("Running every 60s until %s", end_pt.strftime("%Y-%m-%d %H:%M %Z"))

    open_trades: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []

    def close_trade(t: dict[str, Any]) -> None:
        try:
            o = _order(tc, t["contract"], buy=False)
            exit_px = _filled_price(tc, o.id) or t["entry"]
        except Exception as exc:  # noqa: BLE001
            log.warning("close failed for %s: %s", t["contract"], exc)
            exit_px = t["entry"]
        pnl = round((exit_px - t["entry"]) * 100 * QTY, 2)
        t.update(exit=exit_px, pnl=pnl, right=pnl > 0, closed_at=datetime.now(UTC).isoformat())
        closed.append(t)

    while datetime.now(PT) < end_pt:
        try:
            now = datetime.now(UTC)
            # 1) Close held positions whose window elapsed.
            for t in [x for x in open_trades if now >= x["exit_at"]]:
                close_trade(t)
                open_trades.remove(t)
            # 2) New decision (only while market open + under the concurrency cap).
            clk = tc.get_clock()
            if clk.is_open and len(open_trades) < MAX_OPEN:
                side, price = spy_direction(sd)
                if side in ("CALL", "PUT") and price > 0:
                    c = pick_contract(tc, side, price)
                    if c is not None:
                        o = _order(tc, c.symbol, buy=True)
                        entry = _filled_price(tc, o.id)
                        if entry is not None:
                            open_trades.append(
                                {
                                    "contract": c.symbol,
                                    "side": side,
                                    "strike": float(c.strike_price),
                                    "expiry": str(c.expiration_date),
                                    "spy": round(price, 2),
                                    "entry": entry,
                                    "opened_at": now.isoformat(),
                                    "exit_at": now + timedelta(minutes=HOLD_MIN),
                                }
                            )
                            log.info("BUY %s %s @ %.2f (SPY %.2f)", side, c.symbol, entry, price)
            _write_report(closed, open_trades, now_pt)
        except Exception as exc:  # noqa: BLE001
            log.warning("tick error: %s", exc)
        time.sleep(60)

    # End of window: try to close whatever is still open.
    for t in list(open_trades):
        close_trade(t)
        open_trades.remove(t)
    _write_report(closed, open_trades, now_pt)
    log.info("Done. %d decisions, total upside $%.2f", len(closed), sum(t["pnl"] for t in closed))


if __name__ == "__main__":
    main()
