"""
SVM alert playbook — deterministic rule evaluation over stored FRED series.

Every alert returns {id, name, pattern, fired, value, detail, series}. Missing or
insufficient data → the alert is returned with fired=False and a "no data" detail
(skipped, never a crash, never a fabricated signal).
"""

from __future__ import annotations

from typing import Any

Point = dict[str, Any]  # {"date": iso str, "value": float}
SeriesMap = dict[str, list[Point]]


# ── helpers (pure) ────────────────────────────────────────────────────────────


def values(series: list[Point]) -> list[float]:
    return [p["value"] for p in series]


def yoy(series: list[Point], periods: int = 12) -> list[Point]:
    """Year-over-year % for a regular monthly series."""
    out: list[Point] = []
    for i in range(periods, len(series)):
        prev = series[i - periods]["value"]
        if prev:
            out.append({"date": series[i]["date"], "value": (series[i]["value"] / prev - 1) * 100})
    return out


def income_series(hours: list[Point], earnings: list[Point]) -> list[Point]:
    """Weekly wage income = avg hours × avg hourly earnings (joined on date)."""
    by_date = {p["date"]: p["value"] for p in earnings}
    return [
        {"date": p["date"], "value": p["value"] * by_date[p["date"]]}
        for p in hours
        if p["date"] in by_date
    ]


def rolling_mean(series: list[Point], n: int) -> list[Point]:
    out: list[Point] = []
    vals = values(series)
    for i in range(n - 1, len(vals)):
        out.append({"date": series[i]["date"], "value": sum(vals[i - n + 1 : i + 1]) / n})
    return out


def spread(a: list[Point], b: list[Point]) -> list[Point]:
    bd = {p["date"]: p["value"] for p in b}
    return [{"date": p["date"], "value": p["value"] - bd[p["date"]]} for p in a if p["date"] in bd]


def _alert(
    aid: str, name: str, pattern: str, series: list[str], fired: bool, value: Any, detail: str
) -> dict[str, Any]:
    return {
        "id": aid,
        "name": name,
        "pattern": pattern,
        "series": series,
        "fired": bool(fired),
        "value": value,
        "detail": detail,
    }


def _nodata(aid: str, name: str, pattern: str, series: list[str]) -> dict[str, Any]:
    return _alert(aid, name, pattern, series, False, None, "insufficient data")


# ── alert rules ───────────────────────────────────────────────────────────────


def evaluate_alerts(data: SeriesMap) -> list[dict[str, Any]]:  # noqa: PLR0915
    alerts: list[dict[str, Any]] = []
    cpi_yoy = yoy(data.get("CPIAUCSL", []))
    ppi_yoy = yoy(data.get("PPIFIS", []))
    core_ppi_yoy = yoy(data.get("WPSFD4131", []))
    inc_yoy = yoy(income_series(data.get("AWHNONAG", []), data.get("AHETPI", [])))
    dgs2 = data.get("DGS2", [])
    dff = data.get("DFF", [])
    icsa = data.get("ICSA", [])
    ccsa = data.get("CCSA", [])

    # 1 — policy mistake: CPI YoY falling over 3 months while policy rate flat/rising
    if len(cpi_yoy) >= 4 and len(dff) >= 70:
        cpi_falling = cpi_yoy[-1]["value"] < cpi_yoy[-4]["value"]
        rate_not_cutting = dff[-1]["value"] >= dff[-63]["value"] - 0.05  # ~3 months of days
        alerts.append(
            _alert(
                "policy_mistake",
                "CPI rolling over while policy rate flat/rising",
                "crossover",
                ["CPIAUCSL", "DFF"],
                cpi_falling and rate_not_cutting,
                round(cpi_yoy[-1]["value"], 2),
                f"CPI YoY {cpi_yoy[-4]['value']:.1f}%→{cpi_yoy[-1]['value']:.1f}% over 3m; "
                f"Fed funds {dff[-63]['value']:.2f}%→{dff[-1]['value']:.2f}%",
            )
        )
    else:
        alerts.append(
            _nodata(
                "policy_mistake",
                "CPI rolling over while policy rate flat/rising",
                "crossover",
                ["CPIAUCSL", "DFF"],
            )
        )

    # 2 — real wages negative: CPI YoY > income YoY
    if cpi_yoy and inc_yoy:
        c, w = cpi_yoy[-1]["value"], inc_yoy[-1]["value"]
        alerts.append(
            _alert(
                "real_wages_negative",
                "Real wages negative (CPI above wage income, YoY)",
                "crossover",
                ["CPIAUCSL", "AWHNONAG", "AHETPI"],
                c > w,
                round(c - w, 2),
                f"CPI {c:.1f}% vs income {w:.1f}% — spread {c - w:+.1f}pts",
            )
        )
    else:
        alerts.append(
            _nodata(
                "real_wages_negative",
                "Real wages negative (CPI above wage income, YoY)",
                "crossover",
                ["CPIAUCSL", "AWHNONAG", "AHETPI"],
            )
        )

    # 3 — income−CPI spread falling 3 consecutive months
    if len(cpi_yoy) >= 4 and len(inc_yoy) >= 4:
        sp = spread(inc_yoy, cpi_yoy)
        if len(sp) >= 4:
            falling = all(sp[i]["value"] < sp[i - 1]["value"] for i in range(-3, 0))
            alerts.append(
                _alert(
                    "income_spread_falling_3m",
                    "Income−CPI spread falling 3 straight months",
                    "trend",
                    ["CPIAUCSL", "AWHNONAG", "AHETPI"],
                    falling,
                    round(sp[-1]["value"], 2),
                    "spread last 4m: " + ", ".join(f"{q['value']:.1f}" for q in sp[-4:]),
                )
            )
        else:
            alerts.append(
                _nodata(
                    "income_spread_falling_3m",
                    "Income−CPI spread falling 3 straight months",
                    "trend",
                    ["CPIAUCSL", "AWHNONAG", "AHETPI"],
                )
            )
    else:
        alerts.append(
            _nodata(
                "income_spread_falling_3m",
                "Income−CPI spread falling 3 straight months",
                "trend",
                ["CPIAUCSL", "AWHNONAG", "AHETPI"],
            )
        )

    # 4 — divergence: CPI YoY rising while 2Y fell over ~20 trading days
    if len(cpi_yoy) >= 2 and len(dgs2) >= 21:
        cpi_up = cpi_yoy[-1]["value"] > cpi_yoy[-2]["value"]
        d2_down = dgs2[-1]["value"] < dgs2[-21]["value"]
        alerts.append(
            _alert(
                "cpi_up_2y_down",
                "CPI rising while the 2-year yield falls (bond market disagrees)",
                "crossover",
                ["CPIAUCSL", "DGS2"],
                cpi_up and d2_down,
                round(dgs2[-1]["value"] - dgs2[-21]["value"], 3),
                f"CPI {cpi_yoy[-2]['value']:.1f}%→{cpi_yoy[-1]['value']:.1f}%; "
                f"2Y {dgs2[-21]['value']:.2f}→{dgs2[-1]['value']:.2f}",
            )
        )
    else:
        alerts.append(
            _nodata(
                "cpi_up_2y_down",
                "CPI rising while the 2-year yield falls (bond market disagrees)",
                "crossover",
                ["CPIAUCSL", "DGS2"],
            )
        )

    # 5 — 2Y below 3.5% (rate-cut pricing)
    if dgs2:
        alerts.append(
            _alert(
                "two_year_below_3_5",
                "2-year yield below 3.5% (cuts being priced)",
                "threshold",
                ["DGS2"],
                dgs2[-1]["value"] < 3.5,
                round(dgs2[-1]["value"], 2),
                f"2Y at {dgs2[-1]['value']:.2f}%",
            )
        )
    else:
        alerts.append(
            _nodata(
                "two_year_below_3_5",
                "2-year yield below 3.5% (cuts being priced)",
                "threshold",
                ["DGS2"],
            )
        )

    # 6 — PPI hot but core rolling: headline−core > 1.5pts and core falling
    if ppi_yoy and len(core_ppi_yoy) >= 2:
        gap = ppi_yoy[-1]["value"] - core_ppi_yoy[-1]["value"]
        core_falling = core_ppi_yoy[-1]["value"] < core_ppi_yoy[-2]["value"]
        alerts.append(
            _alert(
                "ppi_hot_core_rolling",
                "Headline PPI >1.5pts above core while core rolls over",
                "crossover",
                ["PPIFIS", "WPSFD4131"],
                gap > 1.5 and core_falling,
                round(gap, 2),
                f"headline {ppi_yoy[-1]['value']:.1f}% vs core {core_ppi_yoy[-1]['value']:.1f}%",
            )
        )
    else:
        alerts.append(
            _nodata(
                "ppi_hot_core_rolling",
                "Headline PPI >1.5pts above core while core rolls over",
                "crossover",
                ["PPIFIS", "WPSFD4131"],
            )
        )

    # 7 — margin squeeze: CPI YoY − PPI YoY < 0
    if cpi_yoy and ppi_yoy:
        sp7 = spread(cpi_yoy, ppi_yoy)
        if sp7:
            alerts.append(
                _alert(
                    "margin_squeeze",
                    "CPI−PPI spread negative (corporate margins squeezed)",
                    "crossover",
                    ["CPIAUCSL", "PPIFIS"],
                    sp7[-1]["value"] < 0,
                    round(sp7[-1]["value"], 2),
                    f"spread {sp7[-1]['value']:+.1f}pts",
                )
            )
        else:
            alerts.append(
                _nodata(
                    "margin_squeeze",
                    "CPI−PPI spread negative (corporate margins squeezed)",
                    "crossover",
                    ["CPIAUCSL", "PPIFIS"],
                )
            )
    else:
        alerts.append(
            _nodata(
                "margin_squeeze",
                "CPI−PPI spread negative (corporate margins squeezed)",
                "crossover",
                ["CPIAUCSL", "PPIFIS"],
            )
        )

    # 8 — claims: 4-wk avg > 250k; weekly spike >15% above 4-wk avg
    if len(icsa) >= 5:
        avg4 = rolling_mean(icsa, 4)
        alerts.append(
            _alert(
                "claims_4wk_above_250k",
                "Initial claims 4-week average above 250k",
                "threshold",
                ["ICSA"],
                avg4[-1]["value"] > 250_000,
                int(avg4[-1]["value"]),
                f"4-wk avg {avg4[-1]['value']:,.0f}",
            )
        )
        spike = icsa[-1]["value"] > 1.15 * avg4[-2]["value"] if len(avg4) >= 2 else False
        alerts.append(
            _alert(
                "claims_spike_15pct",
                "Weekly claims >15% above the 4-week average",
                "threshold",
                ["ICSA"],
                spike,
                int(icsa[-1]["value"]),
                f"week {icsa[-1]['value']:,.0f} vs 4-wk avg {avg4[-2]['value']:,.0f}"
                if len(avg4) >= 2
                else "n/a",
            )
        )
    else:
        alerts.append(
            _nodata(
                "claims_4wk_above_250k",
                "Initial claims 4-week average above 250k",
                "threshold",
                ["ICSA"],
            )
        )
        alerts.append(
            _nodata(
                "claims_spike_15pct",
                "Weekly claims >15% above the 4-week average",
                "threshold",
                ["ICSA"],
            )
        )

    # 9 — continuing claims rising 4 consecutive weeks; 12-month high
    if len(ccsa) >= 5:
        rising = all(ccsa[i]["value"] > ccsa[i - 1]["value"] for i in range(-4, 0))
        alerts.append(
            _alert(
                "continuing_claims_rising_4w",
                "Continuing claims rising 4 straight weeks",
                "trend",
                ["CCSA"],
                rising,
                int(ccsa[-1]["value"]),
                "last 5 weeks: " + ", ".join(f"{q['value'] / 1e6:.2f}M" for q in ccsa[-5:]),
            )
        )
        window = values(ccsa[-52:])
        alerts.append(
            _alert(
                "continuing_claims_12m_high",
                "Continuing claims at a 12-month high",
                "threshold",
                ["CCSA"],
                ccsa[-1]["value"] >= max(window),
                int(ccsa[-1]["value"]),
                f"now {ccsa[-1]['value']:,.0f} vs 12m max {max(window):,.0f}",
            )
        )
    else:
        alerts.append(
            _nodata(
                "continuing_claims_rising_4w",
                "Continuing claims rising 4 straight weeks",
                "trend",
                ["CCSA"],
            )
        )
        alerts.append(
            _nodata(
                "continuing_claims_12m_high",
                "Continuing claims at a 12-month high",
                "threshold",
                ["CCSA"],
            )
        )

    # 10 — ECB hike met by falling German 10Y (market rejects the hike)
    ecb = data.get("ECBDFR", [])
    de10 = data.get("IRLTLT01DEM156N", [])
    if len(ecb) >= 2 and len(de10) >= 2:
        hiked = ecb[-1]["value"] > ecb[-2]["value"]
        bund_fell = de10[-1]["value"] < de10[-2]["value"]
        alerts.append(
            _alert(
                "ecb_hike_market_rejects",
                "ECB hiked while German 10Y fell (market overrules the central bank)",
                "event",
                ["ECBDFR", "IRLTLT01DEM156N"],
                hiked and bund_fell,
                round(ecb[-1]["value"], 2),
                f"ECB {ecb[-2]['value']:.2f}%→{ecb[-1]['value']:.2f}%; "
                f"DE10Y {de10[-2]['value']:.2f}→{de10[-1]['value']:.2f}",
            )
        )
    else:
        alerts.append(
            _nodata(
                "ecb_hike_market_rejects",
                "ECB hiked while German 10Y fell (market overrules the central bank)",
                "event",
                ["ECBDFR", "IRLTLT01DEM156N"],
            )
        )

    return alerts


def evaluate_technicals(closes_by_symbol: dict[str, list[float]]) -> list[dict[str, Any]]:
    """Pattern-4 technical alerts on SPY/IGV/SMH closes (oldest→newest)."""
    from app.macro.registry import TECHNICALS

    out: list[dict[str, Any]] = []
    for spec in TECHNICALS:
        sym, ma_n, direction = spec["symbol"], spec["ma"], spec["direction"]
        closes = closes_by_symbol.get(sym, [])
        aid = spec["id"]
        name = f"{sym} {'below' if direction == 'below' else 'above'} its {ma_n}-day MA"
        if len(closes) < ma_n + 1:
            out.append(_nodata(aid, name, "technical", [sym]))
            continue
        ma = sum(closes[-ma_n:]) / ma_n
        px = closes[-1]
        fired = px < ma if direction == "below" else px > ma
        out.append(
            _alert(
                aid,
                name,
                "technical",
                [sym],
                fired,
                round(px, 2),
                f"{sym} {px:.2f} vs {ma_n}dMA {ma:.2f}",
            )
        )
    return out
