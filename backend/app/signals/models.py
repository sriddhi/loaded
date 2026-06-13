"""Pydantic models for the SPY signals API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HorizonSignal(BaseModel):
    horizon_min: int
    label: str
    confidence: float
    reason: str = ""
    # Backtest verdict once the horizon has elapsed: "pending" | "correct" | "wrong".
    outcome: str = "pending"


class SpySignal(BaseModel):
    ts: datetime
    symbol: str = "SPY"
    price: float
    volume: int = 0
    osc: float | None = None  # RSI 0-100 (oversold → overbought); None until enough data
    signals: list[HorizonSignal]


class SpySignalHistory(BaseModel):
    signals: list[SpySignal]
