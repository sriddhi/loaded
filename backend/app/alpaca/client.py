"""
Alpaca TradingClient factory.

Keeps full backward compatibility with app.alpaca_client (used by health endpoint).
New code imports from here; legacy code continues to import from app.alpaca_client.
"""

import os

try:
    from alpaca.trading.client import TradingClient

    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False


def paper_trading_enabled() -> bool:
    return os.getenv("ALPACA_PAPER_TRADE", "true").lower() != "false"


def alpaca_configured() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))


def alpaca_ok() -> tuple[bool, str | None]:
    if not _ALPACA_AVAILABLE:
        return False, "alpaca package not installed"
    if not alpaca_configured():
        return False, "missing_credentials"
    try:
        client = get_trading_client()
        client.get_account()
        return True, None
    except Exception as exc:
        return False, str(exc)


def get_trading_client() -> "TradingClient":
    """Return a configured TradingClient. Raises RuntimeError if credentials missing."""
    if not _ALPACA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("Alpaca credentials not configured")
    return TradingClient(api_key, secret_key, paper=paper_trading_enabled())
