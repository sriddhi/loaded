"""
Pure, deterministic composite scoring (DISCOVER pillar).

Six pillar scorers (0-100) over preloaded inputs; missing data → pillar None
and the composite renormalizes over available weights. Never raises. Labels
are a symmetric ladder gated by coverage and the value/quality pillars.
Educational heuristics only — not financial advice.
"""

from __future__ import annotations

import json
import os
from typing import Any, TypedDict

# ── weights ───────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "value": 0.25,
    "quality": 0.20,
    "growth": 0.15,
    "momentum": 0.15,
    "analyst": 0.15,
    "macro_fit": 0.10,
}


def weights() -> dict[str, float]:
    raw = os.getenv("SCREENER_WEIGHTS", "").strip()
    if not raw:
        return dict(DEFAULT_WEIGHTS)
    try:
        override = json.loads(raw)
        return {k: float(override.get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}
    except (ValueError, TypeError, AttributeError):
        return dict(DEFAULT_WEIGHTS)


# Macro alert id → GICS sector point tilts (applied only while the alert fires).
SECTOR_TILT: dict[str, dict[str, int]] = {
    "real_wages_negative": {"Consumer Discretionary": -12, "Consumer Staples": 8},
    "income_spread_falling_3m": {"Consumer Discretionary": -10, "Consumer Staples": 6},
    "claims_4wk_above_250k": {"Consumer Discretionary": -15, "Consumer Staples": 10},
    "claims_spike_15pct": {"Consumer Discretionary": -8, "Industrials": -6},
    "continuing_claims_rising_4w": {"Consumer Discretionary": -8, "Financials": -5},
    "continuing_claims_12m_high": {"Consumer Discretionary": -8, "Real Estate": -5},
    "policy_mistake": {"Financials": -8, "Utilities": 6, "Real Estate": 5},
    "two_year_below_3_5": {"Utilities": 8, "Real Estate": 8, "Financials": -5},
    "cpi_up_2y_down": {"Utilities": 5, "Consumer Staples": 5},
    "margin_squeeze": {"Industrials": -8, "Materials": -8, "Consumer Staples": -5},
    "ppi_hot_core_rolling": {"Materials": -6, "Energy": 5},
    "ecb_hike_market_rejects": {"Financials": -4},
    "spy_21dma": {"Information Technology": -5, "Consumer Discretionary": -5, "Utilities": 4},
    "igv_50dma": {"Information Technology": 8},
    "smh_50dma": {"Information Technology": 10},
}


class SymbolInputs(TypedDict, total=False):
    symbol: str
    sector: str | None
    statements: list[dict[str, Any]]  # annual rows, newest first
    analyst: dict[str, Any] | None
    closes: list[float]  # ascending daily closes
    price: float | None
    fired_alert_ids: set[str]
    sector_pe_median: float | None


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def _ratio(num: Any, den: Any) -> float | None:
    try:
        n, d = float(num), float(den)
        return n / d if d else None
    except (TypeError, ValueError):
        return None


def _band(x: float | None, lo: float, hi: float, *, invert: bool = False) -> float | None:
    """Linear 0-100 band: x<=lo → 0, x>=hi → 100 (swapped when invert)."""
    if x is None:
        return None
    if hi == lo:
        return None
    t = _clamp((x - lo) / (hi - lo) * 100)
    return 100 - t if invert else t


# ── pillar scorers ────────────────────────────────────────────────────────────


def score_value(inp: SymbolInputs) -> tuple[float | None, list[str]]:
    from app.fundamentals.dcf import run_dcf
    from app.fundamentals.models import EquityFinancials

    stmts = inp.get("statements") or []
    price = inp.get("price")
    reasons: list[str] = []
    dcf_score: float | None = None
    if stmts and price:
        try:
            series = [
                EquityFinancials(
                    **{k: v for k, v in row.items() if k in EquityFinancials.model_fields}
                )
                for row in stmts
            ]
            result: dict[str, Any] = run_dcf(series, price)
            verdict = result.get("verdict")
            upside = float(result.get("upside_pct") or 0.0)
            if verdict == "undervalued":
                dcf_score = _clamp(75 + min(25.0, upside / 2))
                reasons.append(
                    f"Value: DCF undervalued — price ${price:.0f} is {upside:.0f}% below intrinsic"
                )
            elif verdict == "fair":
                dcf_score = _clamp(50 + upside / 4)
                reasons.append(f"Value: DCF fair value (upside {upside:+.0f}%)")
            elif verdict == "overvalued":
                dcf_score = _clamp(max(5.0, 25 + upside / 4))
                reasons.append(f"Value: DCF overvalued ({upside:+.0f}% vs intrinsic)")
        except Exception:  # noqa: BLE001 — value pillar degrades, never crashes
            dcf_score = None
    # relative P/E vs sector median
    rel: float | None = None
    med = inp.get("sector_pe_median")
    if price and stmts and med and med > 0:
        eps = stmts[0].get("eps_diluted")
        try:
            pe = price / float(eps) if eps and float(eps) > 0 else None
        except (TypeError, ValueError):
            pe = None
        if pe and pe > 0:
            # below sector median → bonus up to +15, above → down to −15
            rel = _clamp(50 + max(-15.0, min(15.0, (med - pe) / med * 30)))
            if pe < med:
                reasons.append(f"Value: P/E {pe:.0f} below sector median {med:.0f}")
    if dcf_score is None and rel is None:
        return None, []
    if dcf_score is None:
        return rel, reasons
    if rel is None:
        return dcf_score, reasons
    return _clamp(0.7 * dcf_score + 0.3 * rel), reasons


def score_quality(inp: SymbolInputs) -> tuple[float | None, list[str]]:
    stmts = inp.get("statements") or []
    if not stmts:
        return None, []
    latest = stmts[0]
    roe = _ratio(latest.get("net_income"), latest.get("total_equity"))
    net_margin = _ratio(latest.get("net_income"), latest.get("revenue"))
    gross_margin = _ratio(latest.get("gross_profit"), latest.get("revenue"))
    dte = _ratio(latest.get("total_debt"), latest.get("total_equity"))
    cur = _ratio(latest.get("current_assets"), latest.get("current_liabilities"))
    parts = [
        _band(roe, 0.0, 0.20),
        _band(net_margin, 0.0, 0.20),
        _band(gross_margin, 0.10, 0.55),
        _band(dte, 2.0, 0.5) if dte is not None else None,  # lower is better
        _band(cur, 0.8, 1.8),
    ]
    avail = [p for p in parts if p is not None]
    if not avail:
        return None, []
    score = sum(avail) / len(avail)
    reasons = []
    if roe is not None:
        reasons.append(f"Quality: ROE {roe * 100:.0f}%")
    if net_margin is not None:
        reasons.append(f"Quality: net margin {net_margin * 100:.0f}%")
    return _clamp(score), reasons[:2]


def _cagr(newest: Any, oldest: Any, years: int) -> float | None:
    try:
        a, b = float(newest), float(oldest)
        if b <= 0 or a <= 0 or years <= 0:
            return None
        out: float = (a / b) ** (1 / years) - 1
        return out
    except (TypeError, ValueError):
        return None


def _growth_band(g: float | None) -> float | None:
    if g is None:
        return None
    pct = g * 100
    if pct <= 0:
        return _clamp(35 + pct)  # negative growth scales 0-35
    if pct >= 25:
        return 100.0
    if pct <= 10:
        return 40 + pct * 3  # 0→40, 10→70
    return 70 + (pct - 10) * 2  # 10→70, 25→100


def score_growth(inp: SymbolInputs) -> tuple[float | None, list[str]]:
    stmts = inp.get("statements") or []
    if len(stmts) < 4:
        return None, []
    newest, oldest = stmts[0], stmts[3]
    rev_g = _cagr(newest.get("revenue"), oldest.get("revenue"), 3)
    eps_g = _cagr(newest.get("eps_diluted"), oldest.get("eps_diluted"), 3)
    parts = [p for p in (_growth_band(rev_g), _growth_band(eps_g)) if p is not None]
    if not parts:
        return None, []
    reasons = []
    if rev_g is not None:
        reasons.append(f"Growth: revenue {rev_g * 100:+.0f}%/yr (3y)")
    if eps_g is not None:
        reasons.append(f"Growth: EPS {eps_g * 100:+.0f}%/yr (3y)")
    return _clamp(sum(parts) / len(parts)), reasons


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def score_momentum(inp: SymbolInputs) -> tuple[float | None, list[str]]:
    closes = inp.get("closes") or []
    if len(closes) < 210:
        return None, []
    px = closes[-1]
    ma50 = sum(closes[-50:]) / 50
    ma200 = sum(closes[-200:]) / 200
    score = 0.0
    reasons: list[str] = []
    above = (px > ma50) + (px > ma200)
    score += 40 if above == 2 else (20 if above == 1 else 0)
    if above == 2:
        reasons.append("Momentum: above 50 & 200DMA")
    elif above == 0:
        reasons.append("Momentum: below both moving averages")
    rsi = _rsi(closes)
    if rsi is not None:
        if 45 <= rsi <= 65:
            score += 20
        elif rsi > 75:
            score -= 10
            reasons.append(f"Momentum: RSI {rsi:.0f} overbought")
        elif rsi < 30:
            score += 10
            reasons.append(f"Momentum: RSI {rsi:.0f} oversold (contrarian)")
    r3m = px / closes[-63] - 1 if len(closes) >= 63 else 0.0
    r6m = px / closes[-126] - 1 if len(closes) >= 126 else 0.0
    score += _clamp((r3m + r6m) * 100) * 0.4
    if r3m or r6m:
        reasons.append(f"Momentum: 3m {r3m * 100:+.0f}%, 6m {r6m * 100:+.0f}%")
    return _clamp(score), reasons[:2]


_REC_MAP = {"strong_buy": 100.0, "buy": 75.0, "hold": 50.0, "sell": 25.0, "strong_sell": 0.0}


def score_analyst(inp: SymbolInputs) -> tuple[float | None, list[str]]:
    a = inp.get("analyst")
    price = inp.get("price")
    if not a:
        return None, []
    target = a.get("target_price_mean")
    rec = str(a.get("recommendation") or "").lower().replace(" ", "_")
    n = int(a.get("num_analysts") or 0)
    parts = 0.0
    weight_sum = 0.0
    reasons: list[str] = []
    if target and price:
        upside = (float(target) / price - 1) * 100
        up_score = _clamp(40 + upside * 2)  # 0%→40, +30%→100, −20%→0
        parts += up_score * 0.6
        weight_sum += 0.6
        reasons.append(f"Analysts: mean target {upside:+.0f}% vs price")
    if rec in _REC_MAP:
        parts += _REC_MAP[rec] * 0.4
        weight_sum += 0.4
        reasons.append(f"Analysts: consensus {rec.replace('_', ' ')} ({n})")
    if weight_sum == 0:
        return None, []
    score = parts / weight_sum
    if 0 < n < 5:
        score = 50 + (score - 50) / 2  # low coverage → shrink toward neutral
    return _clamp(score), reasons


def score_macro_fit(inp: SymbolInputs) -> tuple[float | None, list[str]]:
    sector = inp.get("sector")
    fired = inp.get("fired_alert_ids") or set()
    if not sector:
        return None, []
    tilt = 0
    hits: list[str] = []
    for aid in fired:
        delta = SECTOR_TILT.get(aid, {}).get(sector, 0)
        if delta:
            tilt += delta
            hits.append(f"{aid} {delta:+d}")
    reasons = [f"Macro: {sector} tilt {tilt:+d} ({', '.join(sorted(hits))})"] if hits else []
    return _clamp(50 + tilt), reasons


# ── composite + labels ────────────────────────────────────────────────────────


def composite(scores: dict[str, float | None]) -> tuple[float | None, float]:
    w = weights()
    total_w = sum(w.values())
    avail = {k: s for k, s in scores.items() if s is not None}
    if not avail:
        return None, 0.0
    used_w = sum(w[k] for k in avail)
    comp = sum(s * w[k] for k, s in avail.items()) / used_w
    return round(comp, 1), round(used_w / total_w, 3)


def label(comp: float | None, coverage: float, value: float | None, quality: float | None) -> str:
    if comp is None or coverage < 0.5:
        return "hold"
    v = value if value is not None else 50.0
    q = quality if quality is not None else 50.0
    if comp >= 75 and coverage >= 0.8 and v >= 60 and q >= 60:
        return "strong_buy"
    if comp >= 60:
        return "buy"
    if comp < 25 and coverage >= 0.8 and v <= 40 and q <= 40:
        return "strong_sell"
    if comp < 40 and coverage >= 0.6:
        return "sell"
    return "hold"


def score_symbol(inp: SymbolInputs) -> dict[str, Any]:
    """Deterministic full evaluation of one symbol. Never raises."""
    pillar_fns = {
        "value": score_value,
        "quality": score_quality,
        "growth": score_growth,
        "momentum": score_momentum,
        "analyst": score_analyst,
        "macro_fit": score_macro_fit,
    }
    scores: dict[str, float | None] = {}
    reasons: list[str] = []
    for name, fn in pillar_fns.items():
        try:
            s, r = fn(inp)
        except Exception:  # noqa: BLE001 — a pillar bug must not kill the night
            s, r = None, []
        scores[name] = round(s, 1) if s is not None else None
        reasons.extend(r)
    comp, cov = composite(scores)
    cand = label(comp, cov, scores["value"], scores["quality"])
    if cov < 0.5:
        reasons.append(f"insufficient data (coverage {cov * 100:.0f}%)")
    price = inp.get("price")
    return {
        "symbol": inp.get("symbol", ""),
        "composite": comp,
        "pillars": scores,
        "coverage": cov,
        "candidate": cand,
        "price_cents": round(price * 100) if price else None,
        "reasons": reasons[:10],
        "inputs": {
            "sector": inp.get("sector"),
            "n_statements": len(inp.get("statements") or []),
            "n_closes": len(inp.get("closes") or []),
            "has_analyst": bool(inp.get("analyst")),
            "fired_alerts": sorted(inp.get("fired_alert_ids") or set()),
        },
    }
