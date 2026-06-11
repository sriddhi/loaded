"""
Deterministic outlook: a heuristic fair-value estimate, a multi-horizon
buy/sell/neutral call with confidence, and category tags (growth/value/…).

Everything here is a transparent, rule-based heuristic computed from statements +
price momentum + the forward EPS estimate. It is NOT a prediction and NOT
financial advice — short horizons especially are inherently low-confidence.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

HORIZONS = ["1d", "1w", "1mo", "1y", "3y", "5y"]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def compute_fair_value(
    forward_eps: float | None, rev_growth: float | None
) -> dict[str, Any] | None:
    """A PEG-style fair value: forward EPS × a growth-scaled multiple.

    Multiple = 15 baseline, +1 per point of YoY revenue growth, capped 8–40. Range
    is ±18%. Deterministic; None when we lack a positive forward EPS.
    """
    if forward_eps is None or forward_eps <= 0:
        return None
    growth_pts = (rev_growth or 0.0) * 100.0
    multiple = _clamp(15.0 + growth_pts, 8.0, 40.0)
    value = round(forward_eps * multiple, 2)
    return {
        "value": value,
        "low": round(value * 0.82, 2),
        "high": round(value * 1.18, 2),
        "multiple": round(multiple, 1),
        "method": "forward EPS × growth-scaled P/E (heuristic)",
    }


def category_tags(
    *,
    rev_growth: float | None,
    pe: float | None,
    pb: float | None,
    roe: float | None,
    net_margin: float | None,
    debt_to_equity: float | None,
    net_income: float | None,
) -> list[str]:
    """Deterministic style/quality tags from the latest fundamentals."""
    tags: list[str] = []
    if rev_growth is not None and rev_growth >= 0.15:
        tags.append("growth")
    if (pe is not None and 0 < pe < 15) and (pb is not None and 0 < pb < 2):
        tags.append("value")
    if (roe is not None and roe >= 0.15) and (net_margin is not None and net_margin >= 0.15):
        tags.append("quality")
    if debt_to_equity is not None and debt_to_equity >= 1.5:
        tags.append("high-leverage")
    if net_income is not None:
        tags.append("profitable" if net_income > 0 else "unprofitable")
    if not tags:
        tags.append("mixed")
    return tags


def _label(score: float) -> str:
    if score >= 0.15:
        return "buy"
    if score <= -0.15:
        return "sell"
    return "neutral"


def _conf(score: float, cap: int) -> int:
    """Confidence 0–100 from |score|, capped by horizon certainty."""
    return int(_clamp(round(abs(score) * 140), 5, cap))


def horizon_outlook(
    *,
    returns: dict[str, float | None],
    upside_pct: float | None,
    rev_growth: float | None,
    roe: float | None,
    net_margin: float | None,
) -> list[dict[str, Any]]:
    """Per-horizon buy/sell/neutral + confidence.

    `returns` = trailing fractional returns keyed '5d','10d','21d','126d','252d'.
    Short horizons lean technical (momentum); long horizons lean fundamental
    (valuation upside + growth + quality). Short horizons are confidence-capped.
    """
    r5 = returns.get("5d") or 0.0
    r10 = returns.get("10d") or 0.0
    r21 = returns.get("21d") or 0.0
    r252 = returns.get("252d") or 0.0
    up = (upside_pct or 0.0) / 100.0  # fraction
    g = rev_growth or 0.0
    quality = ((roe or 0.0) + (net_margin or 0.0)) / 2.0

    # Per-horizon score in roughly [-1, 1], and a confidence cap.
    specs: dict[str, tuple[float, int]] = {
        "1d": (_clamp(r5 * 6, -1, 1), 45),
        "1w": (_clamp(r10 * 5, -1, 1), 55),
        "1mo": (_clamp(r21 * 4, -1, 1), 65),
        "1y": (_clamp(up * 1.5 + r252 * 0.5 + g, -1, 1), 80),
        "3y": (_clamp(up * 1.2 + g * 1.5 + quality, -1, 1), 85),
        "5y": (_clamp(up + g * 2.0 + quality * 1.2, -1, 1), 88),
    }
    out: list[dict[str, Any]] = []
    for h in HORIZONS:
        score, cap = specs[h]
        out.append({"horizon": h, "label": _label(score), "confidence": _conf(score, cap)})
    return out


def daily_closes(symbol: str, days: int = 260) -> list[float]:
    """Trailing daily closes (oldest→newest) via yfinance; [] on failure."""
    import yfinance as yf

    try:
        hist = yf.Ticker(symbol).history(period=f"{days + 10}d", interval="1d")
        if hist is None or hist.empty:
            return []
        return [float(c) for c in hist["Close"].tail(days)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[outlook] closes fetch failed for %s: %s", symbol, exc)
        return []


def returns_from_closes(closes: list[float]) -> dict[str, float | None]:
    """Trailing fractional returns over common lookbacks from a close series (old→new)."""
    out: dict[str, float | None] = {}
    n = len(closes)
    last = closes[-1] if n else 0.0
    for key, lb in (("5d", 5), ("10d", 10), ("21d", 21), ("126d", 126), ("252d", 252)):
        if n > lb and closes[-lb - 1] > 0:
            out[key] = (last - closes[-lb - 1]) / closes[-lb - 1]
        else:
            out[key] = None
    return out
