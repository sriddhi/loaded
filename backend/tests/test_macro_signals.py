"""Tests for the SVM macro alert rules — fired and not-fired paths."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-only")

from app.macro.signals import (  # noqa: E402
    evaluate_alerts,
    evaluate_technicals,
    income_series,
    rolling_mean,
    spread,
    yoy,
)


def _monthly(values: list[float], start_year: int = 2020) -> list[dict]:
    out = []
    for i, v in enumerate(values):
        y, m = divmod(i, 12)
        out.append({"date": f"{start_year + y}-{m + 1:02d}-01", "value": v})
    return out


def _daily(values: list[float]) -> list[dict]:
    return [
        {"date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", "value": v}
        for i, v in enumerate(values)
    ]


def _get(alerts: list[dict], aid: str) -> dict:
    return next(a for a in alerts if a["id"] == aid)


def test_helpers_yoy_income_spread_rolling():
    cpi = _monthly([100.0] * 12 + [105.0])
    assert abs(yoy(cpi)[-1]["value"] - 5.0) < 1e-9
    hours = _monthly([34.0, 34.0])
    earn = _monthly([30.0, 31.0])
    inc = income_series(hours, earn)
    assert inc[-1]["value"] == 34.0 * 31.0
    sp = spread(_monthly([3.0, 2.0]), _monthly([1.0, 1.0]))
    assert sp[-1]["value"] == 1.0
    rm = rolling_mean(_monthly([1, 2, 3, 4.0]), 2)
    assert rm[-1]["value"] == 3.5


def test_real_wages_negative_fires_and_clears():
    # CPI growing 6%, income growing ~2% → real wages negative fires.
    cpi = _monthly([100 * (1.005**i) for i in range(26)])
    hours = _monthly([34.0] * 26)
    earn = _monthly([30 * (1.0016**i) for i in range(26)])
    data = {"CPIAUCSL": cpi, "AWHNONAG": hours, "AHETPI": earn}
    assert _get(evaluate_alerts(data), "real_wages_negative")["fired"] is True
    # Income growing faster than CPI → not fired.
    data["AHETPI"] = _monthly([30 * (1.01**i) for i in range(26)])
    assert _get(evaluate_alerts(data), "real_wages_negative")["fired"] is False


def test_margin_squeeze_sign():
    cpi = _monthly([100 * (1.002**i) for i in range(26)])  # ~2.4% YoY
    ppi = _monthly([100 * (1.005**i) for i in range(26)])  # ~6% YoY → spread negative
    fired = _get(evaluate_alerts({"CPIAUCSL": cpi, "PPIFIS": ppi}), "margin_squeeze")
    assert fired["fired"] is True and fired["value"] < 0
    calm = _get(evaluate_alerts({"CPIAUCSL": ppi, "PPIFIS": cpi}), "margin_squeeze")
    assert calm["fired"] is False


def test_two_year_threshold_and_divergence():
    dgs2_low = _daily([3.4] * 30)
    out = evaluate_alerts({"DGS2": dgs2_low})
    assert _get(out, "two_year_below_3_5")["fired"] is True
    # CPI accelerating while 2Y falls over 20 obs → divergence fires.
    cpi = _monthly([100.0] * 12 + [102.0, 104.5])  # YoY rising at the end
    dgs2 = _daily([4.0] * 10 + [3.9 - i * 0.01 for i in range(25)])
    fired = _get(evaluate_alerts({"CPIAUCSL": cpi, "DGS2": dgs2}), "cpi_up_2y_down")
    assert fired["fired"] is True


def test_claims_rules():
    icsa_hot = [{"date": f"2026-01-{i + 1:02d}", "value": 260_000.0} for i in range(6)]
    out = evaluate_alerts({"ICSA": icsa_hot})
    assert _get(out, "claims_4wk_above_250k")["fired"] is True
    assert _get(out, "claims_spike_15pct")["fired"] is False  # flat, no spike
    icsa_spike = icsa_hot[:-1] + [{"date": "2026-01-07", "value": 320_000.0}]
    assert _get(evaluate_alerts({"ICSA": icsa_spike}), "claims_spike_15pct")["fired"] is True


def test_continuing_claims_rules():
    rising = [{"date": f"2026-01-{i + 1:02d}", "value": 1_700_000 + i * 10_000.0} for i in range(6)]
    out = evaluate_alerts({"CCSA": rising})
    assert _get(out, "continuing_claims_rising_4w")["fired"] is True
    assert _get(out, "continuing_claims_12m_high")["fired"] is True
    falling = list(reversed(rising))
    out2 = evaluate_alerts({"CCSA": falling})
    assert _get(out2, "continuing_claims_rising_4w")["fired"] is False


def test_ecb_hike_market_rejects():
    ecb = _monthly([2.0, 2.25])
    de10 = _monthly([3.08, 3.05])
    assert (
        _get(evaluate_alerts({"ECBDFR": ecb, "IRLTLT01DEM156N": de10}), "ecb_hike_market_rejects")[
            "fired"
        ]
        is True
    )


def test_missing_data_never_crashes():
    out = evaluate_alerts({})
    assert len(out) >= 11
    assert all(a["fired"] is False for a in out)
    assert all(a["detail"] == "insufficient data" for a in out)


def test_technicals():
    closes_below = [100.0] * 30 + [90.0]  # below 21dMA
    out = evaluate_technicals({"SPY": closes_below, "IGV": [], "SMH": [100.0] * 60})
    spy = next(a for a in out if a["id"] == "spy_21dma")
    assert spy["fired"] is True
    igv = next(a for a in out if a["id"] == "igv_50dma")
    assert igv["fired"] is False and igv["detail"] == "insufficient data"
