"""
BUILD pillar — deterministic portfolio health checks + sizing suggestions.

Pure functions over valued holdings (dicts with symbol/sector/weight_pct/
market_value/cost_basis) and latest screener scores. Educational guidance
only — every consumer labels output as not financial advice.
"""

from __future__ import annotations

from typing import Any

# S&P 500 GICS sector reference weights (approx., 2026-06; update with releases).
SP500_SECTOR_WEIGHTS: dict[str, float] = {
    "Information Technology": 33.0,
    "Financials": 13.5,
    "Health Care": 10.5,
    "Consumer Discretionary": 10.5,
    "Communication Services": 9.5,
    "Industrials": 8.5,
    "Consumer Staples": 5.5,
    "Energy": 3.0,
    "Utilities": 2.5,
    "Real Estate": 2.0,
    "Materials": 1.5,
}

POSITION_WARN_PCT, POSITION_FLAG_PCT = 10.0, 20.0
SECTOR_WARN_PTS, SECTOR_FLAG_PTS = 10.0, 20.0
BREADTH_WARN, BREADTH_FLAG = 10, 5
HHI_WARN, HHI_FLAG = 0.10, 0.18
CASH_DRAG_PCT = 20.0
SELL_VALUE_WARN_PCT = 25.0
MAX_POSITION_TARGET_PCT = 10.0


def _value(h: dict[str, Any]) -> float:
    return float(h.get("market_value") or h.get("cost_basis") or 0.0)


def _weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    total = sum(_value(h) for h in holdings)
    if total <= 0:
        return {}
    return {str(h["symbol"]): _value(h) / total * 100 for h in holdings}


def _sector_weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    from app.screener.scoring import normalize_sector

    total = sum(_value(h) for h in holdings)
    if total <= 0:
        return {}
    out: dict[str, float] = {}
    for h in holdings:
        sector = str(normalize_sector(h.get("sector")) or "Unknown")
        out[sector] = out.get(sector, 0.0) + _value(h) / total * 100
    return out


def run_health_checks(
    holdings: list[dict[str, Any]],
    cash_pct: float,
    latest_scores: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """All checks, always returned (status ok when fine)."""
    checks: list[dict[str, Any]] = []
    w = _weights(holdings)
    sw = _sector_weights(holdings)
    scores = latest_scores or {}

    # 1 — single-position concentration
    worst = max(w.items(), key=lambda kv: kv[1], default=(None, 0.0))
    status = (
        "flag" if worst[1] > POSITION_FLAG_PCT else "warn" if worst[1] > POSITION_WARN_PCT else "ok"
    )
    checks.append(
        {
            "id": "position_concentration",
            "status": status,
            "headline": "Single-position concentration",
            "detail": (
                f"{worst[0]} is {worst[1]:.1f}% of equity" if worst[0] else "No equity positions"
            ),
            "metric": round(worst[1], 1),
        }
    )

    # 2 — sector overweight vs S&P reference
    over = []
    worst_delta = 0.0
    for sector, pct in sw.items():
        ref = SP500_SECTOR_WEIGHTS.get(sector, 2.0)
        delta = pct - ref
        worst_delta = max(worst_delta, delta)
        if delta > SECTOR_WARN_PTS:
            over.append(f"{sector} {pct:.0f}% vs index {ref:.0f}%")
    status = (
        "flag"
        if worst_delta > SECTOR_FLAG_PTS
        else "warn"
        if worst_delta > SECTOR_WARN_PTS
        else "ok"
    )
    checks.append(
        {
            "id": "sector_overweight",
            "status": status,
            "headline": "Sector tilt vs S&P 500",
            "detail": "; ".join(over) if over else "No sector more than 10pts overweight",
            "metric": round(worst_delta, 1),
        }
    )

    # 3 — breadth
    n = len(holdings)
    status = "flag" if n < BREADTH_FLAG else "warn" if n < BREADTH_WARN else "ok"
    checks.append(
        {
            "id": "min_breadth",
            "status": status,
            "headline": "Number of holdings",
            "detail": f"{n} holdings (10+ gives meaningful diversification)",
            "metric": float(n),
        }
    )

    # 4 — HHI
    hhi = sum((x / 100) ** 2 for x in w.values())
    status = "flag" if hhi > HHI_FLAG else "warn" if hhi > HHI_WARN else "ok"
    checks.append(
        {
            "id": "hhi",
            "status": status,
            "headline": "Concentration (HHI)",
            "detail": f"HHI {hhi:.2f} — "
            + (
                "concentrated"
                if hhi > HHI_FLAG
                else "moderate"
                if hhi > HHI_WARN
                else "diversified"
            ),
            "metric": round(hhi, 4),
        }
    )

    # 5 — cash drag
    status = "info" if cash_pct > CASH_DRAG_PCT else "ok"
    checks.append(
        {
            "id": "cash_drag",
            "status": status,
            "headline": "Cash level",
            "detail": f"{cash_pct:.1f}% in cash"
            + (" — uninvested cash drags long-run returns" if status == "info" else ""),
            "metric": round(cash_pct, 1),
        }
    )

    # 6 — value held in sell-ranked names
    sell_pct = sum(
        pct
        for sym, pct in w.items()
        if str(scores.get(sym, {}).get("candidate", "")) in ("sell", "strong_sell")
    )
    sell_names = [
        sym for sym in w if str(scores.get(sym, {}).get("candidate", "")) in ("sell", "strong_sell")
    ]
    status = "warn" if sell_pct > SELL_VALUE_WARN_PCT else "ok"
    checks.append(
        {
            "id": "score_quality",
            "status": status,
            "headline": "Holdings the screener ranks sell",
            "detail": (
                f"{sell_pct:.0f}% of equity in sell-ranked names ({', '.join(sell_names)})"
                if sell_names
                else "No holdings currently rank sell"
            ),
            "metric": round(sell_pct, 1),
        }
    )
    return checks


def diversification_score(holdings: list[dict[str, Any]]) -> int:
    """0-100 blend: breadth 30%, 1−HHI 30%, sector count 25%, max position 15%."""
    if not holdings:
        return 0
    w = _weights(holdings)
    breadth = min(len(holdings) / 15, 1.0)
    hhi = sum((x / 100) ** 2 for x in w.values())
    hhi_part = max(0.0, 1.0 - (hhi - 1.0 / len(holdings)) / 0.25) if holdings else 0.0
    hhi_part = min(1.0, hhi_part)
    sectors = len({str(h.get("sector") or "Unknown") for h in holdings})
    sector_part = min(sectors / 6, 1.0)
    max_pos = max(w.values(), default=0.0)
    pos_part = 1.0 if max_pos <= MAX_POSITION_TARGET_PCT else max(0.0, 1 - (max_pos - 10) / 40)
    score = 100 * (0.30 * breadth + 0.30 * hhi_part + 0.25 * sector_part + 0.15 * pos_part)
    return round(min(100.0, max(0.0, score)))


def suggest_allocation(
    cash: float,
    mode: str,
    holdings: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Educational sizing illustration — equal-weight top-ups or score-weighted adds."""
    if cash <= 0:
        return []
    total_after = sum(_value(h) for h in holdings) + cash
    cap_value = total_after * MAX_POSITION_TARGET_PCT / 100
    out: list[dict[str, Any]] = []

    if mode == "equal_weight" and holdings:
        target = total_after / max(len(holdings), 1)
        gaps = sorted(((target - _value(h), h) for h in holdings), key=lambda t: -t[0])
        remaining = cash
        for gap, h in gaps:
            if gap <= 0 or remaining <= 0:
                continue
            spend = min(gap, remaining, cap_value)
            price = h.get("price") or (_value(h) / float(h["qty"]) if h.get("qty") else None)
            if not price:
                continue
            qty = round(spend / price, 2)
            if qty < 0.1:
                continue
            remaining -= qty * price
            out.append(
                {
                    "symbol": h["symbol"],
                    "action": "add",
                    "suggested_qty": qty,
                    "est_cost": round(qty * price, 2),
                    "target_weight_pct": round(target / total_after * 100, 1),
                    "reason": f"Top up toward equal weight (currently {_value(h) / total_after * 100:.1f}%)",
                }
            )
        return out

    held = {str(h["symbol"]) for h in holdings}
    picks = [c for c in candidates if c.get("symbol") not in held][:top_n]
    total_score = sum(float(c.get("composite") or 0) for c in picks)
    if not picks or total_score <= 0:
        return []
    for c in picks:
        share = float(c.get("composite") or 0) / total_score
        spend = min(cash * share, cap_value)
        price = c.get("price")
        if not price:
            continue
        qty = round(spend / price, 2)
        if qty < 0.1:
            continue
        out.append(
            {
                "symbol": c["symbol"],
                "action": "new",
                "suggested_qty": qty,
                "est_cost": round(qty * price, 2),
                "target_weight_pct": round(spend / total_after * 100, 1),
                "reason": f"{c.get('candidate', 'buy').replace('_', ' ')} — composite {c.get('composite')}",
            }
        )
    return out
