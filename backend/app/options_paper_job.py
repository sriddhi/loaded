"""
SPY 0-3 DTE options paper-trading job — multi-strategy, time-boxed experiment.

Every minute it pulls recent SPY 1-minute bars and evaluates EACH strategy:
  - `momentum`        : ~5-min price momentum (up → call, down → put).
  - `bbands_macd_vol` : Bollinger-band mean reversion confirmed by MACD histogram
                        and above-average volume.
For every strategy that fires, while the market is open, it BUYS one near-ATM
0-3 DTE option (call/put) on the Alpaca PAPER account, holds briefly, closes, and
scores the decision right/wrong by realized P&L. A live JSON report documents
every trade with its strategy tag plus per-strategy and combined tallies.

Both strategies trade identically — 1 contract per decision (same sizing) — so the
report is an apples-to-apples comparison.

SAFETY — hard guarantees:
- PAPER ONLY: every client is `TradingClient(paper=True)`; aborts without paper
  credentials. Never touches a real-money account.
- LONG OPTIONS ONLY (buy calls/puts) → max loss is the premium; no writing/naked.
- Time-boxed: stops at OPT_END_PT (default 13:15 America/Los_Angeles); trades only
  while the market clock is open. 1 contract/trade, capped concurrency per strategy.

Run (host or backend container): python -m app.options_paper_job
Report: $OPTIONS_REPORT_PATH (default /app/options_report.json).
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("options_paper_job")

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")

REPORT_PATH = os.getenv("OPTIONS_REPORT_PATH", "/app/options_report.json")
# Time stop (was a blind hold) — the BS grid sweep favored ~45 min for the fade.
HOLD_MIN = int(os.getenv("OPT_HOLD_MIN", "45"))
MAX_OPEN = int(os.getenv("OPT_MAX_OPEN", "5"))  # per strategy
# Option-level exits (fractions of entry premium), from the 8-session sweep:
# TP +50% / SL −50% / 45m time stop → SPY fade hit 58.8%, avg +16.5%/trade.
TAKE_PROFIT = float(os.getenv("OPT_TP", "0.5"))
STOP_LOSS = float(os.getenv("OPT_SL", "0.5"))
# 0.15% / 5-min exhaustion threshold validated best in the sweep.
MOM_THRESHOLD = float(os.getenv("OPT_MOM_THRESHOLD", "0.0015"))
# After a strategy opens, it may not re-enter for this many minutes (stops scalping
# the same drift every bar).
REENTRY_COOLDOWN_MIN = int(os.getenv("OPT_REENTRY_COOLDOWN_MIN", "10"))
END_PT = os.getenv("OPT_END_PT", "13:15")
QTY = 1


# ── Indicators (pure) ─────────────────────────────────────────────────────────


def _ema_series(values: list[float], span: int) -> list[float]:
    k = 2.0 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def macd(closes: list[float]) -> tuple[float, float, float] | None:
    """(macd_line, signal_line, histogram) for MACD(12,26,9); None if too short."""
    if len(closes) < 26:
        return None
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26, strict=False)]
    signal = _ema_series(macd_line, 9)
    return macd_line[-1], signal[-1], macd_line[-1] - signal[-1]


def bollinger(
    closes: list[float], period: int = 20, mult: float = 2.0
) -> tuple[float, float] | None:
    """(%position in [-1,1], bandwidth) — position −1 at lower band, +1 at upper."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    sd = statistics.pstdev(window)
    if sd == 0:
        return 0.0, 0.0
    pos = (closes[-1] - sma) / (mult * sd)
    return max(-2.0, min(2.0, pos)), (mult * sd) / sma


# ── Strategies: bars → ('CALL'|'PUT'|'SKIP', price) ───────────────────────────


def sig_mean_reversion(bars: list[Any]) -> tuple[str, float]:
    """FADE the 5-min move (redesigned from chase-momentum).

    The MU minute-replay showed 5-min moves mean-revert intraday: chasing them was
    35-49% right. So: a sharp up-move → PUT (expect give-back); a sharp down-move
    → CALL (expect bounce).
    """
    closes = [float(b.close) for b in bars]
    if len(closes) < 6:
        return "SKIP", (closes[-1] if closes else 0.0)
    price, ref = closes[-1], closes[-6]
    ret = (price - ref) / ref if ref else 0.0
    if ret >= MOM_THRESHOLD:
        return "PUT", price  # fade the spike
    if ret <= -MOM_THRESHOLD:
        return "CALL", price  # fade the dump
    return "SKIP", price


def sig_bbands_macd_vol(bars: list[Any]) -> tuple[str, float]:
    """Band-touch + MACD *turning* (redesigned).

    The old rule wanted the histogram already opposite-signed at the band — a
    near-contradiction that never fired (at the lower band the histogram is
    almost always negative). New rule: at the band, require the histogram to be
    TURNING (rising at the lower band, falling at the upper) — reversal starting,
    not already finished.
    """
    closes = [float(b.close) for b in bars]
    if len(closes) < 31:
        return "SKIP", (closes[-1] if closes else 0.0)
    bb = bollinger(closes)
    mc_now = macd(closes)
    mc_prev = macd(closes[:-1])
    if bb is None or mc_now is None or mc_prev is None:
        return "SKIP", closes[-1]
    pos, _bw = bb
    hist_now, hist_prev = mc_now[2], mc_prev[2]
    price = closes[-1]
    if pos <= -0.8 and hist_now > hist_prev:
        return "CALL", price  # at/below lower band, downside momentum fading
    if pos >= 0.8 and hist_now < hist_prev:
        return "PUT", price  # at/above upper band, upside momentum fading
    return "SKIP", price


STRATEGIES: list[dict[str, Any]] = [
    {"name": "mean_reversion", "signal": sig_mean_reversion},
    {"name": "bbands_macd_turn", "signal": sig_bbands_macd_vol},
]


# ── Alpaca plumbing ───────────────────────────────────────────────────────────


def _clients() -> tuple[Any, Any]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    key = os.getenv("ALPACA_PAPER_API_KEY")
    sec = os.getenv("ALPACA_PAPER_SECRET_KEY")
    if not key or not sec:
        raise SystemExit("Refusing to run: Alpaca PAPER credentials are not configured.")
    return TradingClient(key, sec, paper=True), StockHistoricalDataClient(key, sec)


def _fetch_bars(stock_client: Any, limit: int = 60) -> list[Any]:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    req = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Minute, limit=limit)
    return list(stock_client.get_stock_bars(req).data.get("SPY", []))


def pick_contract(tc: Any, side: str, price: float) -> Any | None:
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


def _option_last_price(symbol: str) -> float | None:
    """Latest traded price for an option contract (for TP/SL checks)."""
    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionLatestTradeRequest

        oc = OptionHistoricalDataClient(
            os.getenv("ALPACA_PAPER_API_KEY"), os.getenv("ALPACA_PAPER_SECRET_KEY")
        )
        t = oc.get_option_latest_trade(OptionLatestTradeRequest(symbol_or_symbols=symbol))
        return float(t[symbol].price)
    except Exception as exc:  # noqa: BLE001
        log.warning("option quote failed for %s: %s", symbol, exc)
        return None


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


# ── Reporting ─────────────────────────────────────────────────────────────────


def _tally(trades: list[dict[str, Any]]) -> dict[str, Any]:
    right = sum(1 for t in trades if t["right"])
    total = round(sum(t["pnl"] for t in trades), 2)
    return {
        "decisions": len(trades),
        "right": right,
        "wrong": len(trades) - right,
        "win_rate_pct": round(right / len(trades) * 100, 1) if trades else None,
        "total_upside_usd": total,
        "avg_per_trade_usd": round(total / len(trades), 2) if trades else None,
    }


def _write_report(
    closed: list[dict[str, Any]], open_trades: list[dict[str, Any]], start: datetime
) -> None:
    by_strategy: dict[str, list[dict[str, Any]]] = {}
    for t in closed:
        by_strategy.setdefault(t.get("strategy", "?"), []).append(t)
    report = {
        "title": "SPY 0-3 DTE options — multi-strategy paper decision report",
        "account": "ALPACA PAPER (long options only, 1 contract/decision)",
        "started_pt": start.astimezone(PT).strftime("%Y-%m-%d %H:%M %Z"),
        "ends_pt": END_PT + " PT",
        "updated": datetime.now(UTC).isoformat(),
        "by_strategy": {s: _tally(ts) for s, ts in by_strategy.items()},
        "combined": _tally(closed),
        "open_now": {
            s: sum(1 for t in open_trades if t.get("strategy") == s)
            for s in {t.get("strategy") for t in open_trades}
        },
        "trades": closed[-100:],
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)


# ── Main loop ─────────────────────────────────────────────────────────────────


def main() -> None:
    tc, sd = _clients()
    acct = tc.get_account()
    log.info(
        "PAPER account %s · options level %s · buying power %s · strategies: %s",
        getattr(acct, "status", "?"),
        getattr(acct, "options_trading_level", "?"),
        getattr(acct, "buying_power", "?"),
        ", ".join(s["name"] for s in STRATEGIES),
    )

    now_pt = datetime.now(PT)
    hh, mm = (int(x) for x in END_PT.split(":"))
    end_pt = now_pt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end_pt <= now_pt:
        end_pt += timedelta(days=1)
    log.info("Running every 60s until %s", end_pt.strftime("%Y-%m-%d %H:%M %Z"))

    open_trades: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    last_entry: dict[str, datetime] = {}  # strategy → last open time (cooldown)

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
            # 1) exits: option-level take-profit / stop-loss, else the time stop
            for t in list(open_trades):
                due = now >= t["exit_at"]
                px = None if due else _option_last_price(t["contract"])
                if px is not None and t["entry"] > 0:
                    ret = px / t["entry"] - 1
                    if ret >= TAKE_PROFIT:
                        t["exit_reason"] = "take_profit"
                        due = True
                    elif ret <= -STOP_LOSS:
                        t["exit_reason"] = "stop_loss"
                        due = True
                if due:
                    t.setdefault("exit_reason", "time_stop")
                    close_trade(t)
                    open_trades.remove(t)
            # 2) per-strategy decisions while market open
            clk = tc.get_clock()
            if clk.is_open:
                bars = _fetch_bars(sd)
                for strat in STRATEGIES:
                    name = strat["name"]
                    held = sum(1 for t in open_trades if t["strategy"] == name)
                    if held >= MAX_OPEN:
                        continue
                    le = last_entry.get(name)
                    if le is not None and (now - le).total_seconds() < REENTRY_COOLDOWN_MIN * 60:
                        continue  # cooldown — don't re-enter the same drift every minute
                    side, price = strat["signal"](bars)
                    if side not in ("CALL", "PUT") or price <= 0:
                        continue
                    c = pick_contract(tc, side, price)
                    if c is None:
                        continue
                    o = _order(tc, c.symbol, buy=True)
                    entry = _filled_price(tc, o.id)
                    if entry is None:
                        continue
                    open_trades.append(
                        {
                            "strategy": name,
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
                    last_entry[name] = now
                    log.info("[%s] BUY %s %s @ %.2f (SPY %.2f)", name, side, c.symbol, entry, price)
            _write_report(closed, open_trades, now_pt)
        except Exception as exc:  # noqa: BLE001
            log.warning("tick error: %s", exc)
        time.sleep(60)

    for t in list(open_trades):
        close_trade(t)
        open_trades.remove(t)
    _write_report(closed, open_trades, now_pt)
    log.info("Done. %d decisions, total upside $%.2f", len(closed), sum(t["pnl"] for t in closed))


if __name__ == "__main__":
    main()
