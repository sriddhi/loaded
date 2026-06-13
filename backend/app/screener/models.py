"""Pydantic response models for /screener."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

DISCLAIMER = "Heuristic screener — educational ranking, not financial advice."


class UniverseMember(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None


class Pillars(BaseModel):
    value: float | None = None
    quality: float | None = None
    growth: float | None = None
    momentum: float | None = None
    analyst: float | None = None
    macro_fit: float | None = None


class ScoreItem(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    composite: float | None = None
    pillars: Pillars
    coverage: float
    candidate: str
    rank: int | None = None
    price: float | None = None
    reasons: list[str] = []


class ScoresPage(BaseModel):
    as_of: date | None
    total: int
    items: list[ScoreItem]
    disclaimer: str = DISCLAIMER


class ScoreHistoryPoint(BaseModel):
    date: date
    composite: float | None
    candidate: str
    rank: int | None


class ScoreDetail(ScoreItem):
    score_date: date | None = None
    history: list[ScoreHistoryPoint] = []
    disclaimer: str = DISCLAIMER


class ScreenerStatus(BaseModel):
    last_score_date: date | None
    scored: int
    universe_count: int
    running: bool
    last_run_at: datetime | None = None
