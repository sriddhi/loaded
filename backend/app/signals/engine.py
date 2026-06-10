"""
SPY signal engine — a transparent, deterministic heuristic. NOT a prediction.

Given a series of recent 1-minute prices, classify the likely direction over the
next `horizon` minutes as one of:
  bullish | bearish | bull_trap | bear_trap | neutral

Logic (per horizon):
- momentum = return over a horizon-scaled lookback window;
- detect a "trap": a recent extreme (high/low) that price has since reversed away
  from past a threshold — a failed breakout (bull_trap) / failed breakdown
  (bear_trap);
- otherwise classify by momentum sign vs a √horizon-scaled threshold;
- flat or too little data → neutral.
"""

from __future__ import annotations

HORIZONS: list[int] = [5, 10, 20]

# Base move (fraction) that counts as directional over a 1-minute horizon; scales
# with √horizon because volatility grows with time.
_BASE_THRESHOLD = 0.0005


def _threshold(horizon_min: int) -> float:
    return float(_BASE_THRESHOLD * (horizon_min**0.5))


def classify(prices: list[float], horizon_min: int) -> tuple[str, float]:
    """Return (label, confidence in [0,1]) for the next `horizon_min` minutes.

    `prices` are most-recent-last 1-minute samples.
    """
    n = len(prices)
    if n < 4:
        return "neutral", 0.0

    lookback = min(n - 1, max(3, horizon_min))
    window = prices[-(lookback + 1) :]
    start, last = window[0], window[-1]
    if start <= 0:
        return "neutral", 0.0

    ret = (last - start) / start
    hi, lo = max(window), min(window)
    # Index (within window) of the most recent occurrence of the extreme.
    idx_hi = len(window) - 1 - window[::-1].index(hi)
    idx_lo = len(window) - 1 - window[::-1].index(lo)
    drawdown_from_hi = (last - hi) / hi if hi > 0 else 0.0  # <= 0
    rally_from_lo = (last - lo) / lo if lo > 0 else 0.0  # >= 0

    thr = _threshold(horizon_min)
    trap_thr = thr * 1.2
    recent = max(2, len(window) // 4)
    made_recent_high = idx_hi >= len(window) - 1 - recent
    made_recent_low = idx_lo >= len(window) - 1 - recent

    # Failed breakout: pushed to a recent high, now falling away from it.
    if made_recent_high and drawdown_from_hi <= -trap_thr:
        return "bull_trap", _conf(abs(drawdown_from_hi), trap_thr)
    # Failed breakdown: dropped to a recent low, now rallying off it.
    if made_recent_low and rally_from_lo >= trap_thr:
        return "bear_trap", _conf(rally_from_lo, trap_thr)
    if ret >= thr:
        return "bullish", _conf(ret, thr)
    if ret <= -thr:
        return "bearish", _conf(abs(ret), thr)
    return "neutral", _conf(abs(ret), thr)


def _conf(magnitude: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.0
    return round(min(1.0, magnitude / (threshold * 4)), 3)


def compute_all(prices: list[float]) -> dict[int, tuple[str, float]]:
    return {h: classify(prices, h) for h in HORIZONS}
