"""
Alpaca TradingClient factory.

Supports both paper and live accounts via per-request `paper` flag.
Paper is always the default — live requires explicit opt-in.
"""

import os

try:
    from alpaca.trading.client import TradingClient

    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False


def alpaca_configured(paper: bool = True) -> bool:
    """Return True if the credentials for the requested account type are set."""
    if paper:
        return bool(os.getenv("ALPACA_PAPER_API_KEY") and os.getenv("ALPACA_PAPER_SECRET_KEY"))
    return bool(os.getenv("ALPACA_LIVE_API_KEY") and os.getenv("ALPACA_LIVE_SECRET_KEY"))


def get_trading_client(paper: bool = True) -> "TradingClient":
    """Return a configured TradingClient for the requested account type.

    Args:
        paper: True → paper account (default), False → live account.

    Raises:
        RuntimeError: if alpaca-py is not installed or credentials are missing.
    """
    if not _ALPACA_AVAILABLE:
        raise RuntimeError("alpaca-py package is not installed")
    if paper:
        api_key = os.getenv("ALPACA_PAPER_API_KEY")
        secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY")
        if not api_key or not secret_key:
            raise RuntimeError("Alpaca paper credentials not configured")
    else:
        api_key = os.getenv("ALPACA_LIVE_API_KEY")
        secret_key = os.getenv("ALPACA_LIVE_SECRET_KEY")
        if not api_key or not secret_key:
            raise RuntimeError("Alpaca live credentials not configured")
    return TradingClient(api_key, secret_key, paper=paper)


# ── Legacy shims (used by health endpoint in main.py) ─────────────────────────


def alpaca_ok() -> tuple[bool, str | None]:
    """Quick connectivity check — tries paper first, then live."""
    if not _ALPACA_AVAILABLE:
        return False, "alpaca package not installed"
    for use_paper in (True, False):
        if alpaca_configured(use_paper):
            try:
                client = get_trading_client(use_paper)
                client.get_account()
                return True, None
            except Exception as exc:
                return False, str(exc)
    return False, "missing_credentials"
