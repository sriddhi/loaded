"""
0-2 DTE long-option day-trade research — exhaustion-fade with TP/SL exits.

Goal under test: can a LONG-options-only intraday strategy reach a >90% hit rate
with a +50% take-profit? This harness answers empirically instead of asserting:

- Entry: fade an exhaustion move — |5-min return| ≥ threshold (the redesigned
  mean-reversion edge), buy the near-ATM option the other way.
- Exit: option-level take-profit / stop-loss / time stop.
- Option prices are simulated with minute-by-minute Black-Scholes repricing
  (includes theta decay), IV calibrated from the day's realized vol — far more
  honest than a delta proxy, but still a model, not real quotes.

Run:  python -m app.options_research [SYMBOL ...]
Backtest only — no orders. Not a prediction; not financial advice.
"""

from __future__ import annotations

import math
import os
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MINUTES_PER_DAY = 390
TRADING_DAYS = 252


# ── Black-Scholes (r=0) ───────────────────────────────────────────────────────


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, sigma: float, call: bool) -> float:
    """European option price, r=0. Intrinsic at/after expiry."""
    intrinsic = max(spot - strike, 0.0) if call else max(strike - spot, 0.0)
    if t_years <= 0 or sigma <= 0:
        return intrinsic
    sq = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * t_years) / sq
    d2 = d1 - sq
    if call:
        return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def realized_vol_annualized(closes: list[float]) -> float:
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 30:
        return 0.4
    per_min = statistics.pstdev(rets)
    return max(0.15, min(2.0, per_min * math.sqrt(MINUTES_PER_DAY * TRADING_DAYS)))


# ── Backtest one day / one config ─────────────────────────────────────────────


def run_day(
    bars: list[Any],
    *,
    threshold: float,
    tp: float,
    sl: float,
    time_stop_min: int,
    dte: int,
    cooldown_min: int = 10,
    iv_mult: float = 1.0,
) -> list[dict[str, Any]]:
    """Fade entries with BS-repriced option exits. Returns closed trades."""
    closes = [float(b.close) for b in bars]
    times = [b.timestamp.astimezone(ET) for b in bars]
    if len(closes) < 40:
        return []
    sigma = realized_vol_annualized(closes) * iv_mult
    eod = times[0].replace(hour=16, minute=0, second=0, microsecond=0)
    expiry = eod + timedelta(days=dte)

    def t_years(ts: datetime) -> float:
        return float(max(0.0, (expiry - ts).total_seconds())) / (365.0 * 24 * 3600)

    trades: list[dict[str, Any]] = []
    open_t: dict[str, Any] | None = None
    last_entry_idx = -(10**9)

    for i in range(6, len(closes)):
        spot, ts = closes[i], times[i]
        # manage the open position
        if open_t is not None:
            px = bs_price(spot, open_t["strike"], t_years(ts), sigma, open_t["call"])
            ret = px / open_t["entry_px"] - 1 if open_t["entry_px"] > 0 else 0.0
            age = i - open_t["entry_idx"]
            reason = None
            if ret >= tp:
                reason = "tp"
            elif ret <= -sl:
                reason = "sl"
            elif age >= time_stop_min:
                reason = "time"
            elif i == len(closes) - 1:
                reason = "eod"
            if reason:
                open_t.update(exit_ret=ret, exit_reason=reason, win=ret >= tp)
                trades.append(open_t)
                open_t = None
            else:
                continue  # one position at a time
        # entry: fade an exhaustion 5-min move
        if i - last_entry_idx < cooldown_min:
            continue
        ref = closes[i - 5]
        ret5 = (spot - ref) / ref if ref else 0.0
        if abs(ret5) < threshold:
            continue
        call = ret5 <= -threshold  # fade: dump → call, spike → put
        strike = round(spot)  # near-ATM
        entry_px = bs_price(spot, strike, t_years(ts), sigma, call)
        if entry_px < 0.05:
            continue
        open_t = {
            "t": ts.strftime("%m-%d %H:%M"),
            "side": "CALL" if call else "PUT",
            "strike": strike,
            "entry_idx": i,
            "entry_px": entry_px,
            "call": call,
        }
        last_entry_idx = i

    return trades


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"n": 0}
    wins = [t for t in trades if t["win"]]
    rets = [t["exit_ret"] for t in trades]
    expectancy = statistics.fmean(rets)
    return {
        "n": len(trades),
        "hit_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_ret_pct": round(expectancy * 100, 1),
        "expectancy_per_$100": round(expectancy * 100, 1),
        "tp": sum(1 for t in trades if t["exit_reason"] == "tp"),
        "sl": sum(1 for t in trades if t["exit_reason"] == "sl"),
        "time": sum(1 for t in trades if t["exit_reason"] in ("time", "eod")),
    }


# ── Grid sweep ────────────────────────────────────────────────────────────────


def fetch_days(symbol: str, days: int = 5) -> dict[str, list[Any]]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    sd = StockHistoricalDataClient(
        os.environ["ALPACA_PAPER_API_KEY"], os.environ["ALPACA_PAPER_SECRET_KEY"]
    )
    start = datetime.now(UTC) - timedelta(days=days + 5)
    req = StockBarsRequest(
        symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start, limit=10000
    )
    barset: Any = sd.get_stock_bars(req)
    bars = list(barset.data.get(symbol, []))
    by_day: dict[str, list[Any]] = {}
    for b in bars:
        ts = b.timestamp.astimezone(ET)
        if ts.hour < 9 or (ts.hour == 9 and ts.minute < 30) or ts.hour >= 16:
            continue  # RTH only
        by_day.setdefault(ts.strftime("%Y-%m-%d"), []).append(b)
    return by_day


def main() -> None:
    import sys

    symbols = sys.argv[1:] or ["MU", "SPY"]
    grid_threshold = [0.0015, 0.0025, 0.004]
    grid_tp = [0.25, 0.5]
    grid_sl = [0.3, 0.5]
    grid_time = [20, 45]
    grid_dte = [0, 2]

    print("0-2 DTE long-option exhaustion-fade — BS-repriced grid sweep")
    print(f"symbols={symbols}  (TP=take-profit on the option premium)\n")
    rows: list[tuple[Any, ...]] = []
    for sym in symbols:
        by_day = fetch_days(sym)
        days = sorted(by_day)
        print(f"{sym}: {len(days)} sessions ({days[0]}..{days[-1]})")
        for thr in grid_threshold:
            for tp in grid_tp:
                for sl in grid_sl:
                    for tstop in grid_time:
                        for dte in grid_dte:
                            all_trades: list[dict[str, Any]] = []
                            for d in days:
                                all_trades += run_day(
                                    by_day[d],
                                    threshold=thr,
                                    tp=tp,
                                    sl=sl,
                                    time_stop_min=tstop,
                                    dte=dte,
                                )
                            s = summarize(all_trades)
                            if s["n"] >= 5:
                                rows.append(
                                    (
                                        sym,
                                        thr,
                                        tp,
                                        sl,
                                        tstop,
                                        dte,
                                        s["n"],
                                        s["hit_rate"],
                                        s["avg_ret_pct"],
                                    )
                                )
    rows.sort(key=lambda r: (-r[7], -r[8]))
    print("\nTOP CONFIGS by hit-rate (n≥5):")
    print(
        f"{'sym':5} {'thr%':>5} {'tp%':>4} {'sl%':>4} {'time':>4} {'dte':>3} {'n':>4} {'hit%':>6} {'avgRet%':>8}"
    )
    for r in rows[:15]:
        print(
            f"{r[0]:5} {r[1] * 100:5.2f} {r[2] * 100:4.0f} {r[3] * 100:4.0f} {r[4]:4} {r[5]:3} {r[6]:4} {r[7]:6.1f} {r[8]:8.1f}"
        )
    print("\nBEST EXPECTANCY (avg option return/trade):")
    rows.sort(key=lambda r: -r[8])
    for r in rows[:10]:
        print(
            f"{r[0]:5} thr={r[1] * 100:.2f}% tp={r[2] * 100:.0f}% sl={r[3] * 100:.0f}% time={r[4]}m dte={r[5]}  n={r[6]} hit={r[7]}% avgRet={r[8]}%"
        )
    hi = [r for r in rows if r[7] >= 90]
    print(f"\nconfigs reaching ≥90% hit rate: {len(hi)}")


if __name__ == "__main__":
    main()
