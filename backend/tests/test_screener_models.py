"""Response model shapes for /screener."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.screener.models import DISCLAIMER, Pillars, ScoreItem, ScoresPage  # noqa: E402


def test_score_item_defaults():
    item = ScoreItem(symbol="AAPL", pillars=Pillars(), coverage=0.5, candidate="hold")
    assert item.composite is None and item.reasons == []


def test_scores_page_carries_disclaimer():
    page = ScoresPage(as_of=None, total=0, items=[])
    assert "not financial advice" in page.disclaimer
    assert page.disclaimer == DISCLAIMER
