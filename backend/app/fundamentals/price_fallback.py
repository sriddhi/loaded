"""
Price resolution with a REST fallback.

The Finnhub websocket only carries ticks for a handful of subscribed symbols (and
nothing after hours / on the free tier), so symbols like HOOD or KO often have no
live tick — which left their price-based ratios (P/E, P/B, P/S, EV/EBITDA) blank.

`resolve_price` returns the websocket price when present, otherwise falls back to a
yfinance REST quote (short-TTL cached so we don't hammer it). This keeps the
fundamentals page populated for any symbol, with a `source` flag so callers can
show provenance.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.fundamentals.price_cache import PriceStore

logger = logging.getLogger(__name__)

_REST_TTL_MS = 5 * 60 * 1000  # 5 minutes
_rest_cache: dict[str, tuple[float, int]] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _yf_price(symbol: str) -> float | None:
    """Blocking yfinance last-price lookup (fast_info, then a 1-min bar fallback)."""
    import yfinance as yf

    try:
        ticker = yf.Ticker(symbol)
        price: float | None = None
        try:
            fast = ticker.fast_info
            raw = fast.get("last_price") or fast.get("lastPrice")
            price = float(raw) if raw else None
        except Exception:  # noqa: BLE001
            price = None
        if not price or price <= 0:
            hist = ticker.history(period="1d", interval="1m")
            if hist is not None and not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return price if price and price > 0 else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[price-fallback] yfinance lookup failed for %s: %s", symbol, exc)
        return None


async def resolve_price(symbol: str, cache: PriceStore | None) -> tuple[float, int, str] | None:
    """Return (price, ts_ms, source) where source is 'websocket' | 'rest', or None.

    Order: live websocket tick → short-TTL REST cache → fresh yfinance REST quote.
    """
    sym = symbol.upper()
    if cache is not None:
        hit = cache.get(sym)
        if hit is not None:
            return hit[0], hit[1], "websocket"

    cached = _rest_cache.get(sym)
    if cached is not None and (_now_ms() - cached[1]) < _REST_TTL_MS:
        return cached[0], cached[1], "rest"

    price = await asyncio.to_thread(_yf_price, sym)
    if price is None:
        return None
    ts = _now_ms()
    _rest_cache[sym] = (price, ts)
    return price, ts, "rest"
