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


def test_alert_info_covers_every_alert():
    from app.macro.registry import ALERT_INFO
    from app.macro.signals import evaluate_alerts, evaluate_technicals

    ids = {a["id"] for a in evaluate_alerts({})} | {a["id"] for a in evaluate_technicals({})}
    missing = ids - set(ALERT_INFO)
    assert not missing, f"alerts without meaning/impact: {missing}"
    for info in ALERT_INFO.values():
        assert info["meaning"] and info["impact"]
