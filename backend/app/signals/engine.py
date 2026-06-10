"""
SPY signal engine — a transparent, deterministic heuristic. NOT a prediction.

Given a series of recent 1-minute prices, classify the likely direction over the
next `horizon` minutes as one of:
  bullish | bearish | bull_trap | bear_trap | neutral
and return a short reason explaining the rating.

Logic (per horizon):
- momentum = return over a horizon-scaled lookback window;
- detect a "trap": a recent extreme (high/low) that price has since reversed away
  from past a threshold — a failed breakout (bull_trap) / failed breakdown
  (bear_trap);
- otherwise classify by momentum sign vs a √horizon-scaled threshold;
- flat or too little data → neutral.
"""

from __future__ import annotations

# 5m, 10m, 20m, and 1 day (1440 min).
HORIZONS: list[int] = [5, 10, 20, 1440]

# Base move (fraction) that counts as directional over a 1-minute horizon; scales
# with √horizon because volatility grows with time.
_BASE_THRESHOLD = 0.0005


def _threshold(horizon_min: int) -> float:
    return float(_BASE_THRESHOLD * (horizon_min**0.5))


def _fmt_horizon(horizon_min: int) -> str:
    if horizon_min >= 1440:
        return "1 day"
    if horizon_min >= 60:
        return f"{horizon_min // 60}h"
    return f"{horizon_min}m"


def classify(prices: list[float], horizon_min: int) -> tuple[str, float, str]:
    """Return (label, confidence in [0,1], reason) for the next `horizon_min`.

    `prices` are most-recent-last 1-minute samples.
    """
    hz = _fmt_horizon(horizon_min)
    n = len(prices)
    if n < 4:
        return "neutral", 0.0, "Not enough price history yet."

    lookback = min(n - 1, max(3, horizon_min))
    window = prices[-(lookback + 1) :]
    start, last = window[0], window[-1]
    if start <= 0:
        return "neutral", 0.0, "No valid reference price."

    ret = (last - start) / start
    hi, lo = max(window), min(window)
    idx_hi = len(window) - 1 - window[::-1].index(hi)
    idx_lo = len(window) - 1 - window[::-1].index(lo)
    drawdown_from_hi = (last - hi) / hi if hi > 0 else 0.0  # <= 0
    rally_from_lo = (last - lo) / lo if lo > 0 else 0.0  # >= 0

    thr = _threshold(horizon_min)
    trap_thr = thr * 1.2
    recent = max(2, len(window) // 4)
    made_recent_high = idx_hi >= len(window) - 1 - recent
    made_recent_low = idx_lo >= len(window) - 1 - recent
    thr_pct = thr * 100

    if made_recent_high and drawdown_from_hi <= -trap_thr:
        return (
            "bull_trap",
            _conf(abs(drawdown_from_hi), trap_thr),
            f"Pushed to a recent high then fell {abs(drawdown_from_hi) * 100:.2f}% — "
            f"a failed breakout suggests downside risk over the next {hz}.",
        )
    if made_recent_low and rally_from_lo >= trap_thr:
        return (
            "bear_trap",
            _conf(rally_from_lo, trap_thr),
            f"Dropped to a recent low then rallied {rally_from_lo * 100:.2f}% — "
            f"a failed breakdown suggests upside over the next {hz}.",
        )
    if ret >= thr:
        return (
            "bullish",
            _conf(ret, thr),
            f"Up {ret * 100:.2f}% recently, above the {thr_pct:.2f}% move that reads "
            f"directional for the next {hz}.",
        )
    if ret <= -thr:
        return (
            "bearish",
            _conf(abs(ret), thr),
            f"Down {abs(ret) * 100:.2f}% recently, beyond the {thr_pct:.2f}% bar for "
            f"the next {hz}.",
        )
    return (
        "neutral",
        _conf(abs(ret), thr),
        f"Only {ret * 100:+.2f}% move — inside the ±{thr_pct:.2f}% band, so no clear "
        f"edge over the next {hz}.",
    )


def _conf(magnitude: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.0
    return round(min(1.0, magnitude / (threshold * 4)), 3)


def compute_all(prices: list[float]) -> dict[int, tuple[str, float, str]]:
    return {h: classify(prices, h) for h in HORIZONS}
