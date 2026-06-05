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
        client = TradingClient(
            os.environ["ALPACA_API_KEY"],
            os.environ["ALPACA_SECRET_KEY"],
            paper=paper_trading_enabled(),
        )
        client.get_account()
        return True, None
    except Exception as exc:
        return False, str(exc)
