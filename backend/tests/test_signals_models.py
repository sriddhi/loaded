"""Tests for the SPY signals Pydantic models."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.signals.models import HorizonSignal, SpySignal, SpySignalHistory  # noqa: E402


def test_models_round_trip():
    sig = SpySignal(
        ts=datetime.now(UTC),
        price=500.0,
        signals=[HorizonSignal(horizon_min=5, label="bullish", confidence=0.5)],
    )
    assert sig.signals[0].label == "bullish"
    hist = SpySignalHistory(signals=[sig])
    assert len(hist.signals) == 1
    dumped = sig.model_dump()
    assert dumped["price"] == 500.0
