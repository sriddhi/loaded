"""Tests for the ops metrics registry + track_job."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

import pytest  # noqa: E402
from app.ops.metrics import Metrics, track_job  # noqa: E402


def test_record_job_success_updates_counts_and_state():
    m = Metrics()
    m.record_job("j", 12.0)
    snap = m.snapshot()["jobs"][0]
    assert snap["runs"] == 1
    assert snap["errors"] == 0
    assert snap["state"] == "idle"
    assert snap["avg_ms"] == 12.0
    assert snap["last_run"] is not None


def test_record_job_error_sets_error_state_and_rate():
    m = Metrics()
    m.record_job("j", 5.0, ok=True)
    m.record_job("j", 5.0, ok=False, error="boom")
    snap = m.snapshot()["jobs"][0]
    assert snap["runs"] == 2
    assert snap["errors"] == 1
    assert snap["error_rate"] == 0.5
    assert snap["state"] == "error"
    assert snap["last_error"] == "boom"


def test_p95_latency_math():
    m = Metrics()
    for v in range(1, 101):  # 1..100
        m.record_job("j", float(v))
    snap = m.snapshot()["jobs"][0]
    assert snap["p95_ms"] is not None
    assert 90 <= snap["p95_ms"] <= 100


def test_record_api_counts_errors_only_on_4xx_5xx():
    m = Metrics()
    m.record_api("GET", "/x", 200, 10.0)
    m.record_api("GET", "/x", 404, 10.0)
    m.record_api("GET", "/x", 500, 10.0)
    stat = m.snapshot()["api"][0]
    assert stat["calls"] == 3
    assert stat["errors"] == 2
    assert stat["last_status"] == 500
    totals = m.snapshot()["api_totals"]
    assert totals["calls"] == 3
    assert totals["errors"] == 2


def test_track_job_records_success():
    m = Metrics()
    import app.ops.metrics as mod

    original = mod.METRICS
    mod.METRICS = m
    try:
        with track_job("ctx", "ui"):
            pass
    finally:
        mod.METRICS = original
    snap = m.snapshot()["jobs"][0]
    assert snap["name"] == "ctx"
    assert snap["source"] == "ui"
    assert snap["runs"] == 1
    assert snap["errors"] == 0


def test_track_job_records_and_reraises_on_failure():
    m = Metrics()
    import app.ops.metrics as mod

    original = mod.METRICS
    mod.METRICS = m
    try:
        with pytest.raises(ValueError), track_job("ctx", "backend"):
            raise ValueError("nope")
    finally:
        mod.METRICS = original
    snap = m.snapshot()["jobs"][0]
    assert snap["errors"] == 1
    assert snap["state"] == "error"
    assert "ValueError" in (snap["last_error"] or "")
