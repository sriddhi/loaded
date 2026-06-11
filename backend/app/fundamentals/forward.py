"""
Forward valuation — deterministic only.

Forward P/E needs a *forward EPS estimate*, which isn't in our stored statements
(those are trailing/actuals). We pull the analyst forward EPS from yfinance and
compute forward P/E at OUR current resolved price:

    forward_pe = current_price / forward_eps

If forward EPS isn't available, we return None for the forward fields — the UI
shows "—" rather than inventing a number. Cached with a 1-hour TTL (estimates
move slowly and yfinance `.info` is heavy).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_TTL_MS = 60 * 60 * 1000  # 1 hour
_cache: dict[str, tuple[dict[str, float | None], int]] = {}


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # yfinance returns NaN/0 placeholders for missing estimates.
    return f if f == f and f != 0 else None


def _fetch_forward(symbol: str) -> dict[str, float | None]:
    import yfinance as yf

    try:
        info = yf.Ticker(symbol).info
        return {
            "forward_eps": _num(info.get("forwardEps")),
            "trailing_eps": _num(info.get("trailingEps")),
            "forward_pe_provider": _num(info.get("forwardPE")),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[forward] yfinance info failed for %s: %s", symbol, exc)
        return {"forward_eps": None, "trailing_eps": None, "forward_pe_provider": None}


async def forward_metrics(symbol: str, price: float | None) -> dict[str, float | None]:
    """Return {forward_eps, forward_pe, trailing_eps} computed deterministically.

    `forward_pe` is price / forward_eps at the supplied current price; None when
    either the price or the forward EPS estimate is unavailable.
    """
    sym = symbol.upper()
    cached = _cache.get(sym)
    now = int(time.time() * 1000)
    if cached is not None and (now - cached[1]) < _TTL_MS:
        base = cached[0]
    else:
        base = await asyncio.to_thread(_fetch_forward, sym)
        _cache[sym] = (base, now)

    fwd_eps = base.get("forward_eps")
    forward_pe: float | None = None
    if price is not None and fwd_eps is not None and fwd_eps > 0:
        forward_pe = round(price / fwd_eps, 4)
    elif fwd_eps is None:
        # No estimate → leave None (UI shows "—"); do not fall back to a guess.
        forward_pe = None

    return {
        "forward_eps": fwd_eps,
        "trailing_eps": base.get("trailing_eps"),
        "forward_pe": forward_pe,
    }
