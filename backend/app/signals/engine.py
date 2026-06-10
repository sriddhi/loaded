"""
Signal engine — a transparent, deterministic heuristic. NOT a prediction.

Given a series of recent 1-minute prices (and the matching per-minute volumes),
classify the likely direction over the next `horizon` minutes as one of:
  bullish | bearish | bull_trap | bear_trap | neutral
and return a short reason explaining the rating.

Logic (per horizon):
- momentum = return over a horizon-scaled lookback window;
- detect a "trap": a recent extreme (high/low) that price has since reversed away
  from past a threshold — a failed breakout (bull_trap) / failed breakdown
  (bear_trap);
- otherwise classify by momentum sign vs a √horizon-scaled threshold;
- VOLUME confirmation: a directional move is only trustworthy if volume is
  participating. A breakout/breakdown on light volume is downgraded toward a
  trap (an unconfirmed move that tends to fail); a move on heavy volume gets a
  confidence boost. Volume context is woven into every reason when available.
- flat or too little data → neutral.
"""

from __future__ import annotations

# 5m, 10m, 20m, and 1 day (1440 min).
HORIZONS: list[int] = [5, 10, 20, 1440]

# Base move (fraction) that counts as directional over a 1-minute horizon; scales
# with √horizon because volatility grows with time.
_BASE_THRESHOLD = 0.0005

# Volume thresholds (recent volume as a fraction of the baseline average).
_VOL_STRONG = 1.25  # heavy participation — confirms the move
_VOL_WEAK = 0.75  # light participation — weakens conviction
_VOL_TRAP = 0.55  # very light — a directional move here is likely a trap


def _threshold(horizon_min: int) -> float:
    return float(_BASE_THRESHOLD * (horizon_min**0.5))


def _fmt_horizon(horizon_min: int) -> str:
    if horizon_min >= 1440:
        return "1 day"
    if horizon_min >= 60:
        return f"{horizon_min // 60}h"
    return f"{horizon_min}m"


def _vol_ratio(volumes: list[float]) -> float | None:
    """Recent average volume / baseline average volume over the window.

    Returns None when there isn't enough volume data to judge participation.
    """
    vals = [float(v) for v in volumes if v and v > 0]
    if len(vals) < 4:
        return None
    k = max(1, len(vals) // 4)
    recent = vals[-k:]
    baseline = vals[:-k] or vals
    base_avg = sum(baseline) / len(baseline)
    if base_avg <= 0:
        return None
    return (sum(recent) / len(recent)) / base_avg


def _vol_phrase(ratio: float) -> str:
    pct = ratio * 100
    if ratio >= _VOL_STRONG:
        return (
            f"on heavy volume ({pct:.0f}% of its recent average) — strong participation confirms it"
        )
    if ratio <= _VOL_WEAK:
        return f"on light volume ({pct:.0f}% of its recent average) — weak participation, treat with caution"
    return f"on roughly normal volume ({pct:.0f}% of its recent average)"


def classify(
    prices: list[float], volumes: list[float] | None, horizon_min: int
) -> tuple[str, float, str]:
    """Return (label, confidence in [0,1], reason) for the next `horizon_min`.

    `prices` are most-recent-last 1-minute samples. `volumes` is the matching
    per-minute volume series (same alignment); pass None/empty to skip the
    volume check (price-only classification).
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

    vwindow = (volumes or [])[-(lookback + 1) :]
    ratio = _vol_ratio(vwindow)

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

    # ── Price-reversal traps (independent of volume) ──────────────────────────
    if made_recent_high and drawdown_from_hi <= -trap_thr:
        return (
            "bull_trap",
            _conf(abs(drawdown_from_hi), trap_thr, ratio),
            f"Pushed to a recent high then fell {abs(drawdown_from_hi) * 100:.2f}% — "
            f"a failed breakout suggests downside risk over the next {hz}." + _vol_suffix(ratio),
        )
    if made_recent_low and rally_from_lo >= trap_thr:
        return (
            "bear_trap",
            _conf(rally_from_lo, trap_thr, ratio),
            f"Dropped to a recent low then rallied {rally_from_lo * 100:.2f}% — "
            f"a failed breakdown suggests upside over the next {hz}." + _vol_suffix(ratio),
        )

    # ── Directional moves, volume-confirmed ───────────────────────────────────
    if ret >= thr:
        # A breakout on very light volume is an unconfirmed move → bull trap.
        if ratio is not None and ratio <= _VOL_TRAP:
            return (
                "bull_trap",
                _conf(ret, thr, ratio),
                f"Up {ret * 100:.2f}% but {_vol_phrase(ratio)} — an unconfirmed "
                f"breakout like this often fails over the next {hz}.",
            )
        return (
            "bullish",
            _conf(ret, thr, ratio),
            f"Up {ret * 100:.2f}% recently, above the {thr_pct:.2f}% move that reads "
            f"directional for the next {hz}" + _vol_clause(ratio),
        )
    if ret <= -thr:
        if ratio is not None and ratio <= _VOL_TRAP:
            return (
                "bear_trap",
                _conf(abs(ret), thr, ratio),
                f"Down {abs(ret) * 100:.2f}% but {_vol_phrase(ratio)} — an unconfirmed "
                f"breakdown like this often snaps back over the next {hz}.",
            )
        return (
            "bearish",
            _conf(abs(ret), thr, ratio),
            f"Down {abs(ret) * 100:.2f}% recently, beyond the {thr_pct:.2f}% bar for "
            f"the next {hz}" + _vol_clause(ratio),
        )
    return (
        "neutral",
        _conf(abs(ret), thr, ratio),
        f"Only {ret * 100:+.2f}% move — inside the ±{thr_pct:.2f}% band, so no clear "
        f"edge over the next {hz}" + _vol_clause(ratio),
    )


def _vol_clause(ratio: float | None) -> str:
    """Trailing clause that folds volume into a directional/neutral reason."""
    if ratio is None:
        return "."
    return f", {_vol_phrase(ratio)}."


def _vol_suffix(ratio: float | None) -> str:
    """Extra sentence appended to a price-reversal trap reason."""
    if ratio is None:
        return ""
    return f" Volume is {ratio * 100:.0f}% of its recent average."


def _conf(magnitude: float, threshold: float, ratio: float | None = None) -> float:
    """Confidence from move magnitude, scaled by volume participation.

    Heavy volume (ratio ≥ 1.25) boosts conviction up to 1.3×; light volume
    (ratio ≤ 0.75) discounts it down to ~0.6×. No volume data → no adjustment.
    """
    if threshold <= 0:
        return 0.0
    base = min(1.0, magnitude / (threshold * 4))
    if ratio is not None:
        factor = max(0.5, min(1.3, ratio))
        base *= factor
    return round(min(1.0, base), 3)


def compute_all(
    prices: list[float], volumes: list[float] | None = None
) -> dict[int, tuple[str, float, str]]:
    return {h: classify(prices, volumes, h) for h in HORIZONS}
