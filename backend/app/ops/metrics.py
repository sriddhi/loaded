"""
In-process metrics registry — the single source of truth for the Tools tab.

Tracks two things:
- **Jobs** — every background or UI-triggered unit of work (the signal job, the
  backtester, retention, the fundamentals scheduler, UI-triggered refreshes …):
  state, run/error counts, last run, latency (avg + p95), last error.
- **API** — per-endpoint traffic: calls, error count/rate, latency, last status.

It's intentionally in-memory (resets on restart) — a lightweight live view, not a
historical store. Thread-safe via a simple lock since durations may be recorded
from worker threads (e.g. yfinance calls run via asyncio.to_thread).
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_LOCK = threading.Lock()


def _pct(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return round(ordered[idx], 1)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


@dataclass
class JobStat:
    name: str
    source: str  # "backend" | "ui"
    state: str = "idle"  # idle | running | error | stopped
    runs: int = 0
    errors: int = 0
    last_run: str | None = None
    last_duration_ms: float | None = None
    last_error: str | None = None
    _latencies: deque[float] = field(default_factory=lambda: deque(maxlen=200))

    def as_dict(self) -> dict[str, Any]:
        lat = list(self._latencies)
        return {
            "name": self.name,
            "source": self.source,
            "state": self.state,
            "runs": self.runs,
            "errors": self.errors,
            "error_rate": round(self.errors / self.runs, 3) if self.runs else 0.0,
            "last_run": self.last_run,
            "last_duration_ms": self.last_duration_ms,
            "avg_ms": _avg(lat),
            "p95_ms": _pct(lat, 95),
            "last_error": self.last_error,
        }


@dataclass
class ApiStat:
    endpoint: str
    method: str
    calls: int = 0
    errors: int = 0
    last_status: int = 0
    _latencies: deque[float] = field(default_factory=lambda: deque(maxlen=500))

    def as_dict(self) -> dict[str, Any]:
        lat = list(self._latencies)
        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "calls": self.calls,
            "errors": self.errors,
            "error_rate": round(self.errors / self.calls, 3) if self.calls else 0.0,
            "last_status": self.last_status,
            "avg_ms": _avg(lat),
            "p95_ms": _pct(lat, 95),
        }


class Metrics:
    def __init__(self) -> None:
        self.jobs: dict[str, JobStat] = {}
        self.api: dict[str, ApiStat] = {}
        self.started_at = datetime.now(UTC)

    # ── Jobs ──────────────────────────────────────────────────────────────────
    def register_job(self, name: str, source: str = "backend", state: str = "idle") -> None:
        with _LOCK:
            job = self.jobs.setdefault(name, JobStat(name, source))
            job.source = source
            job.state = state

    def set_job_state(self, name: str, state: str, source: str = "backend") -> None:
        with _LOCK:
            self.jobs.setdefault(name, JobStat(name, source)).state = state

    def record_job(
        self,
        name: str,
        duration_ms: float,
        *,
        ok: bool = True,
        error: str | None = None,
        source: str = "backend",
    ) -> None:
        with _LOCK:
            job = self.jobs.setdefault(name, JobStat(name, source))
            job.runs += 1
            job.last_run = datetime.now(UTC).isoformat()
            job.last_duration_ms = round(duration_ms, 1)
            job._latencies.append(duration_ms)
            if ok:
                job.state = "idle"
            else:
                job.errors += 1
                job.last_error = error
                job.state = "error"

    # ── API ───────────────────────────────────────────────────────────────────
    def record_api(self, method: str, endpoint: str, status: int, duration_ms: float) -> None:
        key = f"{method} {endpoint}"
        with _LOCK:
            stat = self.api.setdefault(key, ApiStat(endpoint, method))
            stat.calls += 1
            stat.last_status = status
            stat._latencies.append(duration_ms)
            if status >= 400:
                stat.errors += 1

    # ── Snapshot ──────────────────────────────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        with _LOCK:
            jobs = [j.as_dict() for j in self.jobs.values()]
            api = [a.as_dict() for a in self.api.values()]
        jobs.sort(key=lambda d: (d["source"], d["name"]))
        api.sort(key=lambda d: d["calls"], reverse=True)
        total_calls = sum(a["calls"] for a in api)
        total_errors = sum(a["errors"] for a in api)
        return {
            "uptime_seconds": int((datetime.now(UTC) - self.started_at).total_seconds()),
            "jobs": jobs,
            "api": api,
            "api_totals": {
                "calls": total_calls,
                "errors": total_errors,
                "error_rate": round(total_errors / total_calls, 3) if total_calls else 0.0,
            },
        }


# Module-level singleton — imported wherever work happens.
METRICS = Metrics()


@contextlib.contextmanager
def track_job(name: str, source: str = "backend") -> Iterator[None]:
    """Time a unit of work and record it (success or failure) on METRICS."""
    METRICS.set_job_state(name, "running", source)
    start = time.monotonic()
    ok = True
    err: str | None = None
    try:
        yield
    except Exception as exc:  # noqa: BLE001
        ok = False
        err = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        METRICS.record_job(name, (time.monotonic() - start) * 1000, ok=ok, error=err, source=source)
