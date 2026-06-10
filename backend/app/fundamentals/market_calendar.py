"""
US/NYSE trading-calendar helpers.

Market-day arithmetic (the T+2 earnings age-out, the poll window) must respect
real exchange holidays + early closes — not a weekday approximation. Wraps
`exchange_calendars` (XNYS) behind a tiny interface so the backend can swap it
(e.g. for Alpaca's /v2/calendar) without touching callers.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=1)
def _calendar() -> Any:
    return xcals.get_calendar("XNYS")


def is_trading_day(d: date) -> bool:
    return bool(_calendar().is_session(pd.Timestamp(d)))


def add_trading_days(d: date, n: int) -> date:
    """Return the date n trading days after `d` (n>0) or before (n<0)."""
    cal = _calendar()
    # Anchor to a real session on-or-after (n>=0) / on-or-before (n<0) `d`.
    # date_to_session accepts any date; next/previous_session require a session.
    direction = "next" if n >= 0 else "previous"
    session = cal.date_to_session(pd.Timestamp(d), direction=direction)
    step = cal.next_session if n > 0 else cal.previous_session
    for _ in range(abs(n)):
        session = step(session)
    return date(session.year, session.month, session.day)


def trading_days_between(start: date, end: date) -> int:
    """Number of trading sessions in (start, end] — 0 if end <= start."""
    if end <= start:
        return 0
    sessions = _calendar().sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    # Exclude `start` itself if it is a session; count sessions strictly after it.
    return int(sum(1 for s in sessions if s.date() > start))
