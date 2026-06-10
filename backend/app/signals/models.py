"""Pydantic models for the SPY signals API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HorizonSignal(BaseModel):
    horizon_min: int
    label: str
    confidence: float
    reason: str = ""


class SpySignal(BaseModel):
    ts: datetime
    symbol: str = "SPY"
    price: float
    volume: int = 0
    signals: list[HorizonSignal]


class SpySignalHistory(BaseModel):
    signals: list[SpySignal]
