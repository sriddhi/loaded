"""Registry sanity: every tracker/alert reference resolves."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.macro.registry import SERIES, TECHNICALS, TRACKERS, TTL_HOURS  # noqa: E402


def test_every_tracker_series_is_registered():
    for t in TRACKERS:
        for code in t["series"]:
            assert code in SERIES, f"{t['id']} references unknown series {code}"


def test_frequencies_have_ttls():
    for code, info in SERIES.items():
        assert info["freq"] in TTL_HOURS, f"{code} has unknown freq {info['freq']}"


def test_technicals_shape():
    for spec in TECHNICALS:
        assert spec["direction"] in ("above", "below") and spec["ma"] > 0
