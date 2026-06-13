"""
Buffett-grade DCF — deterministic owner-earnings intrinsic value.

Explicit conservative constraints, all enforced in code (see dcf_generator.md):
owner earnings (OCF − |capex|) with min(latest, 3-yr mean) as the base; growth
derived from history then hard-capped at 15% and faded to a ≤2.5% terminal;
discount rate floored at 8% (+2% leverage penalty); net-debt equity bridge;
quality-scaled 25–50% margin of safety; a 3×3 sensitivity grid; and quality
gates that REFUSE to value erratic or unprofitable cash-flow streams
(`not_valuable` + reasons) rather than fabricate a number.

Heuristic valuation — NOT a prediction, NOT financial advice.
"""

from __future__ import annotations

import os
import statistics
from typing import Any

from app.fundamentals.models import EquityFinancials

GROWTH_CAP = 0.15
TERMINAL_CAP = 0.025
DISCOUNT_FLOOR = 0.08
DISCOUNT_DEFAULT = 0.10
LEVERAGE_PENALTY = 0.02
CV_GATE = 0.6
CV_MOS_BUMP = 0.35
MOS_BASE = 0.30
MOS_MIN, MOS_MAX = 0.25, 0.50
YEARS = 10
STAGE1_YEARS = 5

DISCLAIMER = "Deterministic heuristic DCF — not a prediction, not financial advice."


def _dollars(cents: int | None) -> float | None:
    return cents / 100 if cents is not None else None


def owner_earnings_series(series: list[EquityFinancials]) -> list[float | None]:
    """Owner earnings per period (newest-first), in dollars: OCF − |capex|."""
    out: list[float | None] = []
    for s in series:
        ocf = _dollars(s.operating_cash_flow)
        capex = _dollars(s.capex)
        out.append(ocf - abs(capex) if ocf is not None and capex is not None else None)
    return out


def _cv(values: list[float]) -> float | None:
    """Coefficient of variation (pstdev / |mean|); None when not computable."""
    if len(values) < 3:
        return None
    mean = statistics.fmean(values)
    if mean == 0:
        return None
    return statistics.pstdev(values) / abs(mean)


def quality_gates(series: list[EquityFinancials]) -> tuple[list[str], list[float]]:
    """Return (gate_failures, clean owner-earnings series). Empty failures = pass."""
    failures: list[str] = []
    oe = owner_earnings_series(series)
    known = [v for v in oe if v is not None]
    if len(known) < 4:
        failures.append("insufficient history (<4 annual periods with owner earnings)")
        return failures, known
    last4 = [v for v in oe[:4] if v is not None]
    if oe[0] is not None and oe[0] <= 0:
        failures.append("latest owner earnings non-positive")
    if sum(1 for v in last4 if v <= 0) >= 2:
        failures.append("owner earnings negative in 2+ of the last 4 years")
    cv = _cv(known[:6])
    if cv is not None and cv > CV_GATE:
        failures.append(f"owner earnings too erratic (CV {cv:.2f} > {CV_GATE})")
    shares = series[0].shares_diluted or series[0].shares_outstanding
    if not shares or shares <= 0:
        failures.append("share count missing")
    return failures, known


def _cagr(newest: float, oldest: float, intervals: int) -> float | None:
    if oldest <= 0 or newest <= 0 or intervals < 1:
        return None
    return float((newest / oldest) ** (1 / intervals) - 1)


def derive_growth(series: list[EquityFinancials], oe: list[float]) -> float:
    """Stage-1 growth: min(OE CAGR, revenue CAGR, cap), floored at 0."""
    candidates: list[float] = []
    if len(oe) >= 4:
        g = _cagr(oe[0], oe[min(len(oe), 6) - 1], min(len(oe), 6) - 1)
        if g is not None:
            candidates.append(g)
    revs = [(_dollars(s.revenue) or 0.0) for s in series]
    revs = [r for r in revs if r > 0]
    if len(revs) >= 4:
        g = _cagr(revs[0], revs[min(len(revs), 6) - 1], min(len(revs), 6) - 1)
        if g is not None:
            candidates.append(g)
    if not candidates:
        return 0.0
    return max(0.0, min(min(candidates), GROWTH_CAP))


def discount_rate(debt_to_equity: float | None) -> float:
    try:
        rate = float(os.getenv("DCF_DISCOUNT_RATE", str(DISCOUNT_DEFAULT)))
    except ValueError:
        rate = DISCOUNT_DEFAULT
    rate = max(rate, DISCOUNT_FLOOR)
    if debt_to_equity is not None and debt_to_equity > 1:
        rate += LEVERAGE_PENALTY
    return rate


def two_stage_dcf(base_oe: float, growth: float, discount: float) -> float:
    """PV of 10y owner earnings (stage-1 then linear fade) + Gordon terminal."""
    terminal_g = min(TERMINAL_CAP, discount - 0.01)
    pv = 0.0
    flow = base_oe
    rates: list[float] = []
    for year in range(1, YEARS + 1):
        if year <= STAGE1_YEARS:
            g = growth
        else:  # linear fade from stage-1 to terminal over years 6..10
            step = (growth - terminal_g) / (YEARS - STAGE1_YEARS)
            g = growth - step * (year - STAGE1_YEARS)
        rates.append(g)
        flow *= 1 + g
        pv += flow / (1 + discount) ** year
    terminal_value = flow * (1 + terminal_g) / (discount - terminal_g)
    pv += terminal_value / (1 + discount) ** YEARS
    return pv


def margin_of_safety(
    oe_cv: float | None, debt_to_equity: float | None, roic: float | None
) -> float:
    mos = MOS_BASE
    if roic is not None and roic >= 0.15:
        mos -= 0.05
    if oe_cv is not None and oe_cv > CV_MOS_BUMP:
        mos += 0.10
    if debt_to_equity is not None and debt_to_equity > 1:
        mos += 0.10
    return max(MOS_MIN, min(MOS_MAX, mos))


def sensitivity_grid(
    base_oe: float, growth: float, net_debt: float, shares: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for g in (max(0.0, growth - 0.03), growth, min(GROWTH_CAP, growth + 0.03)):
        cells = []
        for d in (0.08, 0.10, 0.12):
            ev = two_stage_dcf(base_oe, g, d)
            cells.append({"discount": d, "intrinsic": round((ev - net_debt) / shares, 2)})
        rows.append({"growth": round(g, 4), "cells": cells})
    return rows


def _b(usd: float) -> str:
    """Human dollar magnitude."""
    a = abs(usd)
    if a >= 1e9:
        return f"${usd / 1e9:.1f}B"
    if a >= 1e6:
        return f"${usd / 1e6:.0f}M"
    return f"${usd:,.0f}"


def _explain_valued(
    *,
    verdict: str,
    price: float | None,
    intrinsic: float,
    buy_below: float,
    base_oe: float,
    growth: float,
    terminal_g: float,
    discount: float,
    mos: float,
    net_debt: float,
) -> str:
    """A plain-English, savvy-investor read of the valuation (deterministic)."""
    parts: list[str] = []
    # The model in one sentence.
    g_phrase = (
        "assuming no growth (owner earnings have been flat-to-declining over the available history)"
        if growth == 0
        else f"growing ~{growth * 100:.0f}%/yr for 5 years then fading to a {terminal_g * 100:.1f}% terminal rate"
    )
    parts.append(
        f"Valuing {_b(base_oe)} of conservative owner earnings (operating cash flow minus capex), "
        f"{g_phrase}, discounted at {discount * 100:.0f}%"
        + (
            " — including a leverage penalty for debt above equity"
            if discount > DISCOUNT_DEFAULT
            else ""
        )
        + (f", less {_b(net_debt)} of net debt" if abs(net_debt) > 1e6 else "")
        + f" — gives an intrinsic value of about ${intrinsic:,.2f}/share."
    )
    # The gap and what it means.
    if price is not None:
        gap = (intrinsic - price) / price * 100
        direction = "below" if gap < 0 else "above"
        parts.append(
            f"The market price of ${price:,.2f} is {abs(gap):.0f}% {direction} that estimate."
        )
    interp = {
        "undervalued": (
            f"At today's price it clears even the cautious buy-below line of ${buy_below:,.2f} "
            f"(a {mos * 100:.0f}% margin of safety) — the rare case where a conservative model still "
            "leaves room."
        ),
        "fair": (
            f"It sits between the buy-below line (${buy_below:,.2f}, {mos * 100:.0f}% margin of safety) "
            "and intrinsic value — fairly priced, with little margin of safety to protect against the "
            "assumptions being wrong."
        ),
        "overvalued": (
            "The market is paying well more than predictable cash flows justify under these "
            f"deliberately conservative assumptions; you'd want it under ${buy_below:,.2f} "
            f"(a {mos * 100:.0f}% margin of safety) before the math works."
        ),
    }
    parts.append(interp.get(verdict, ""))
    parts.append(
        "This is intentionally strict — it credits only proven, predictable cash generation and "
        "demands a discount before acting. Use it as a sanity check on price, not a target."
    )
    return " ".join(p for p in parts if p)


def run_dcf(
    series: list[EquityFinancials],
    price: float | None,
    *,
    roic: float | None = None,
) -> dict[str, Any]:
    """Full DCF: gates → assumptions → intrinsic/share → verdict. Never raises."""
    failures, oe_known = quality_gates(series)
    if failures:
        return {
            "verdict": "not_valuable",
            "gate_failures": failures,
            "price": price,
            "explanation": (
                "This business doesn't clear the predictability bar a DCF requires ("
                + "; ".join(failures)
                + "). A discounted-cash-flow value here would be precision without accuracy, so the "
                "model declines to print a number rather than anchor you to a false one — exactly what "
                "a disciplined investor does outside their circle of competence."
            ),
            "disclaimer": DISCLAIMER,
        }

    latest = series[0]
    base_oe = min(oe_known[0], statistics.fmean(oe_known[:3]))
    growth = derive_growth(series, oe_known)
    debt = _dollars(latest.total_debt) or 0.0
    cash = _dollars(latest.cash_and_equiv) or 0.0
    equity = _dollars(latest.total_equity)
    d_to_e = (debt / equity) if equity and equity > 0 else None
    discount = discount_rate(d_to_e)
    terminal_g = min(TERMINAL_CAP, discount - 0.01)
    shares = float(latest.shares_diluted or latest.shares_outstanding or 0)
    net_debt = debt - cash
    oe_cv = _cv(oe_known[:6])

    ev = two_stage_dcf(base_oe, growth, discount)
    intrinsic = (ev - net_debt) / shares
    mos = margin_of_safety(oe_cv, d_to_e, roic)
    buy_below = intrinsic * (1 - mos)

    if price is None:
        verdict = "fair"
    elif price < buy_below:
        verdict = "undervalued"
    elif price <= intrinsic:
        verdict = "fair"
    else:
        verdict = "overvalued"

    return {
        "verdict": verdict,
        "gate_failures": [],
        "price": price,
        "intrinsic_per_share": round(intrinsic, 2),
        "buy_below": round(buy_below, 2),
        "upside_pct": round((intrinsic - price) / price * 100, 1) if price else None,
        "explanation": _explain_valued(
            verdict=verdict,
            price=price,
            intrinsic=intrinsic,
            buy_below=buy_below,
            base_oe=base_oe,
            growth=growth,
            terminal_g=terminal_g,
            discount=discount,
            mos=mos,
            net_debt=net_debt,
        ),
        "assumptions": {
            "base_owner_earnings_usd": round(base_oe, 0),
            "stage1_growth": round(growth, 4),
            "terminal_growth": round(terminal_g, 4),
            "discount_rate": round(discount, 4),
            "margin_of_safety": round(mos, 2),
            "net_debt_usd": round(net_debt, 0),
            "shares": shares,
            "owner_earnings_cv": round(oe_cv, 3) if oe_cv is not None else None,
            "debt_to_equity": round(d_to_e, 2) if d_to_e is not None else None,
            "roic": round(roic, 4) if roic is not None else None,
        },
        "sensitivity": sensitivity_grid(base_oe, growth, net_debt, shares),
        "disclaimer": DISCLAIMER,
    }
