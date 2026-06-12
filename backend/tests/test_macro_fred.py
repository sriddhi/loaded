"""Tests for the FRED client (CSV parsing, key switching)."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.macro.fred import _parse_csv, csv_starts, fred_api_key, fred_enabled  # noqa: E402


def test_csv_starts_narrowing_ladder():
    # Full-history request gets the fallback ladder appended.
    assert csv_starts("1990-01-01") == ["1990-01-01", "2018-01-01", "2023-01-01"]
    # Incremental (recent) request needs no fallbacks earlier than itself.
    assert csv_starts("2026-03-01") == ["2026-03-01"]
    # Mid-range request only keeps later fallbacks.
    assert csv_starts("2020-06-01") == ["2020-06-01", "2023-01-01"]


def test_parse_csv_skips_missing_values():
    text = "observation_date,DGS2\n2026-01-02,4.25\n2026-01-03,.\n2026-01-04,4.30\nbad,row\n"
    obs = _parse_csv(text)
    assert len(obs) == 2
    assert obs[0][1] == 4.25 and obs[1][1] == 4.30


def test_parse_csv_empty():
    assert _parse_csv("") == []
    assert _parse_csv("header_only\n") == []


def test_key_detection():
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        assert fred_api_key() == ""
        assert fred_enabled() is True  # CSV fallback keeps the module alive
    with patch.dict(os.environ, {"FRED_API_KEY": "abc"}):
        assert fred_api_key() == "abc"
