"""
Unit tests for Alpaca client factory (app/alpaca/client.py).
"""

import os
from unittest.mock import patch

import pytest


def test_alpaca_configured_paper_false_when_missing():
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY")
    }
    with patch.dict(os.environ, env, clear=True):
        from app.alpaca.client import alpaca_configured

        assert alpaca_configured(paper=True) is False


def test_alpaca_configured_paper_true_when_set():
    with patch.dict(
        os.environ, {"ALPACA_PAPER_API_KEY": "key", "ALPACA_PAPER_SECRET_KEY": "secret"}
    ):
        from app.alpaca.client import alpaca_configured

        assert alpaca_configured(paper=True) is True


def test_alpaca_configured_live_false_when_missing():
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY")
    }
    with patch.dict(os.environ, env, clear=True):
        from app.alpaca.client import alpaca_configured

        assert alpaca_configured(paper=False) is False


def test_alpaca_configured_live_true_when_set():
    with patch.dict(
        os.environ, {"ALPACA_LIVE_API_KEY": "lkey", "ALPACA_LIVE_SECRET_KEY": "lsecret"}
    ):
        from app.alpaca.client import alpaca_configured

        assert alpaca_configured(paper=False) is True


@patch("app.alpaca.client._ALPACA_AVAILABLE", False)
def test_get_trading_client_raises_when_unavailable():
    from app.alpaca.client import get_trading_client

    with pytest.raises(RuntimeError, match="alpaca-py package is not installed"):
        get_trading_client()


def test_get_trading_client_raises_when_no_paper_credentials():
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY")
    }
    with (
        patch.dict(os.environ, env, clear=True),
        patch("app.alpaca.client._ALPACA_AVAILABLE", True),
    ):
        from app.alpaca.client import get_trading_client

        with pytest.raises(RuntimeError, match="paper credentials not configured"):
            get_trading_client(paper=True)


def test_get_trading_client_raises_when_no_live_credentials():
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY")
    }
    with (
        patch.dict(os.environ, env, clear=True),
        patch("app.alpaca.client._ALPACA_AVAILABLE", True),
    ):
        from app.alpaca.client import get_trading_client

        with pytest.raises(RuntimeError, match="live credentials not configured"):
            get_trading_client(paper=False)
