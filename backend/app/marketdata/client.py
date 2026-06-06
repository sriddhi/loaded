"""
Alpaca market data client factory.

Authenticates with paper keys first, then real keys, then unauthenticated
(free indicative/delayed feed). No trading credentials required.
"""

from __future__ import annotations

import os

try:
    from alpaca.data.historical import (
        OptionHistoricalDataClient,
        ScreenerClient,
        StockHistoricalDataClient,
    )
    from alpaca.data.historical.news import NewsClient

    _ALPACA_DATA_AVAILABLE = True
except ImportError:
    _ALPACA_DATA_AVAILABLE = False


def _get_keys() -> tuple[str | None, str | None]:
    """Return best available API key pair (paper → real → None)."""
    api_key = os.getenv("ALPACA_PAPER_API_KEY") or os.getenv("ALPACA_REAL_API_KEY")
    secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY") or os.getenv("ALPACA_REAL_SECRET_KEY")
    if api_key and secret_key:
        return api_key, secret_key
    return None, None


def get_stock_client() -> StockHistoricalDataClient:
    """Return StockHistoricalDataClient. Authenticated if keys present, else free/delayed."""
    if not _ALPACA_DATA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    api_key, secret_key = _get_keys()
    if api_key and secret_key:
        return StockHistoricalDataClient(api_key, secret_key)
    return StockHistoricalDataClient()  # unauthenticated — iex/delayed feed


def get_screener_client() -> ScreenerClient:
    """Return ScreenerClient for movers/actives. Authenticated if keys present."""
    if not _ALPACA_DATA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    api_key, secret_key = _get_keys()
    if api_key and secret_key:
        return ScreenerClient(api_key, secret_key)
    return ScreenerClient()


def get_news_client() -> NewsClient:
    """Return NewsClient. Authenticated if keys present, else free tier."""
    if not _ALPACA_DATA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    api_key, secret_key = _get_keys()
    if api_key and secret_key:
        return NewsClient(api_key, secret_key)
    return NewsClient()


def get_option_client() -> OptionHistoricalDataClient:
    """Return OptionHistoricalDataClient. Authenticated if keys present, else indicative feed."""
    if not _ALPACA_DATA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    api_key, secret_key = _get_keys()
    if api_key and secret_key:
        return OptionHistoricalDataClient(api_key, secret_key)
    return OptionHistoricalDataClient()
