"""
Unit tests for market data client factory (app/marketdata/client.py).
"""

import os
from unittest.mock import patch

import pytest


def test_get_stock_client_authenticated_with_paper_keys():
    with (
        patch.dict(os.environ, {"ALPACA_PAPER_API_KEY": "pk", "ALPACA_PAPER_SECRET_KEY": "ps"}),
        patch("app.marketdata.client._ALPACA_DATA_AVAILABLE", True),
        patch("app.marketdata.client.StockHistoricalDataClient") as mock_cls,
    ):
        from app.marketdata.client import get_stock_client

        get_stock_client()
        mock_cls.assert_called_once_with("pk", "ps")


def test_get_stock_client_unauthenticated_when_no_keys():
    env = {k: v for k, v in os.environ.items() if "ALPACA" not in k}
    with (
        patch.dict(os.environ, env, clear=True),
        patch("app.marketdata.client._ALPACA_DATA_AVAILABLE", True),
        patch("app.marketdata.client.StockHistoricalDataClient") as mock_cls,
    ):
        from app.marketdata.client import get_stock_client

        get_stock_client()
        mock_cls.assert_called_once_with()


def test_get_option_client_authenticated_with_real_keys():
    env = {k: v for k, v in os.environ.items() if "ALPACA" not in k}
    env.update({"ALPACA_REAL_API_KEY": "rk", "ALPACA_REAL_SECRET_KEY": "rs"})
    with (
        patch.dict(os.environ, env, clear=True),
        patch("app.marketdata.client._ALPACA_DATA_AVAILABLE", True),
        patch("app.marketdata.client.OptionHistoricalDataClient") as mock_cls,
    ):
        from app.marketdata.client import get_option_client

        get_option_client()
        mock_cls.assert_called_once_with("rk", "rs")


def test_get_stock_client_raises_when_unavailable():
    with patch("app.marketdata.client._ALPACA_DATA_AVAILABLE", False):
        from app.marketdata.client import get_stock_client

        with pytest.raises(RuntimeError, match="alpaca-py package is not installed"):
            get_stock_client()
