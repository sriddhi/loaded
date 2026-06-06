"""
Unit tests for Alpaca client factory (app/alpaca/client.py).
"""

import os
from unittest.mock import patch

import pytest


def test_paper_trading_enabled_default():
    """paper_trading_enabled() returns True when env var is unset."""
    env = {k: v for k, v in os.environ.items() if k != "ALPACA_PAPER_TRADE"}
    with patch.dict(os.environ, env, clear=True):
        from app.alpaca.client import paper_trading_enabled

        assert paper_trading_enabled() is True


def test_paper_trading_disabled_when_false():
    with patch.dict(os.environ, {"ALPACA_PAPER_TRADE": "false"}):
        from app.alpaca.client import paper_trading_enabled

        assert paper_trading_enabled() is False


def test_alpaca_configured_false_when_missing():
    env = {k: v for k, v in os.environ.items() if k not in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")}
    with patch.dict(os.environ, env, clear=True):
        from app.alpaca.client import alpaca_configured

        assert alpaca_configured() is False


def test_alpaca_configured_true_when_set():
    with patch.dict(os.environ, {"ALPACA_API_KEY": "key", "ALPACA_SECRET_KEY": "secret"}):
        from app.alpaca.client import alpaca_configured

        assert alpaca_configured() is True


@patch("app.alpaca.client._ALPACA_AVAILABLE", False)
def test_get_trading_client_raises_when_unavailable():
    from app.alpaca.client import get_trading_client

    with pytest.raises(RuntimeError, match="alpaca-py package is not installed"):
        get_trading_client()


def test_get_trading_client_raises_when_no_credentials():
    env = {k: v for k, v in os.environ.items() if k not in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")}
    with (
        patch.dict(os.environ, env, clear=True),
        patch("app.alpaca.client._ALPACA_AVAILABLE", True),
    ):
        from app.alpaca.client import get_trading_client

        with pytest.raises(RuntimeError, match="credentials not configured"):
            get_trading_client()
