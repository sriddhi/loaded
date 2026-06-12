"""
FRED data client.

Uses the official FRED API when FRED_API_KEY is set; otherwise falls back to the
keyless public CSV endpoint (fredgraph.csv) so the module works without a key and
upgrades automatically when one appears.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.stlouisfed.org/fred"
CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
DEFAULT_START = "1990-01-01"


def fred_api_key() -> str:
    return os.getenv("FRED_API_KEY", "").strip()


def fred_enabled() -> bool:
    """Always true — the CSV fallback needs no key. Kept for symmetry/tests."""
    return True


def _parse_csv(text: str) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        return out
    for row in reader:
        if len(row) < 2:
            continue
        raw = row[1].strip()
        if raw in (".", "", "NA"):
            continue  # FRED uses '.' for missing values
        try:
            out.append((date.fromisoformat(row[0].strip()), float(raw)))
        except ValueError:
            continue
    return out


# Full-history daily CSVs (e.g. DFF since 1990) take FRED a while to generate.
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)

# fredgraph.csv 504s on long dense windows. When that happens, retry with a
# narrower window — recent data is enough for every tracker/alert; full history
# comes via the official API once FRED_API_KEY is set.
_CSV_FALLBACK_STARTS = ("2018-01-01", "2023-01-01")


def csv_starts(start: str) -> list[str]:
    """The narrowing ladder of start dates to attempt for the CSV endpoint."""
    return [start] + [fb for fb in _CSV_FALLBACK_STARTS if fb > start]


async def fetch_observations(code: str, start: str = DEFAULT_START) -> list[tuple[date, float]]:
    """All (date, value) observations for a series since `start` (ascending)."""
    key = fred_api_key()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        if key:
            resp = await client.get(
                f"{API_BASE}/series/observations",
                params={
                    "series_id": code,
                    "api_key": key,
                    "file_type": "json",
                    "observation_start": start,
                },
            )
            resp.raise_for_status()
            out: list[tuple[date, float]] = []
            for ob in resp.json().get("observations", []):
                raw = ob.get("value", ".")
                if raw in (".", "", None):
                    continue
                try:
                    out.append((date.fromisoformat(ob["date"]), float(raw)))
                except (ValueError, KeyError):
                    continue
            return out
        starts = csv_starts(start)
        for i, s in enumerate(starts):
            resp = await client.get(CSV_BASE, params={"id": code, "cosd": s})
            if resp.status_code in (502, 503, 504) and i < len(starts) - 1:
                logger.info("[fred] CSV %s for %s from %s; narrowing", resp.status_code, code, s)
                continue
            resp.raise_for_status()
            return _parse_csv(resp.text)
        return []  # unreachable; keeps mypy satisfied


async def fetch_meta(code: str) -> dict[str, str]:
    """Series metadata (title, last_updated). Best-effort; {} without a key."""
    key = fred_api_key()
    if not key:
        return {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{API_BASE}/series",
                params={"series_id": code, "api_key": key, "file_type": "json"},
            )
            resp.raise_for_status()
            seriess = resp.json().get("seriess", [])
            if seriess:
                return {
                    "title": seriess[0].get("title", ""),
                    "last_updated": seriess[0].get("last_updated", ""),
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fred] meta fetch failed for %s: %s", code, exc)
    return {}
