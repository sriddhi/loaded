"""Validation rules on portfolio request models."""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.portfolio.models import PortfolioCreate, TransactionCreate  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def test_portfolio_name_required():
    with pytest.raises(ValidationError):
        PortfolioCreate(name="")
    assert PortfolioCreate(name="Growth").name == "Growth"


def test_tx_type_enum_enforced():
    with pytest.raises(ValidationError):
        TransactionCreate(tx_type="short", trade_date=date(2026, 1, 2))


def test_tx_positive_quantities():
    with pytest.raises(ValidationError):
        TransactionCreate(
            tx_type="buy", symbol="AAPL", qty=-1, price=10, trade_date=date(2026, 1, 2)
        )
    ok = TransactionCreate(
        tx_type="buy", symbol="AAPL", qty=1.5, price=10.25, trade_date=date(2026, 1, 2)
    )
    assert ok.qty == 1.5 and ok.fees == 0.0
