# Generator — `fundamentals` DCF (Buffett-grade intrinsic value)

**Module:** `fundamentals` (`backend/app/fundamentals/**`), endpoint
`GET /fundamentals/{symbol}/dcf`.

## Purpose
A deterministic, owner-earnings DCF with the explicit conservative constraints a
Buffett-style investor applies. Every assumption is derived from stored data,
hard-capped, and echoed back — fully auditable, no LLM in the loop. When a
business fails the quality gates, the engine **refuses to produce a number**
(`not_valuable` + reasons): no number is better than a wrong number.

**Heuristic valuation tool — NOT a prediction, NOT financial advice. Read-only.**

## Inputs
Annual statements series (newest-first, ≥4 periods required): operating_cash_flow,
capex, free_cash_flow, revenue, net_income, total_debt, cash_and_equiv,
shares_diluted/shares_outstanding (all integer cents / share counts). Current
price via `resolve_price`. Reuse `_load_series`, `_refresh_then_track`,
`safe_div`/`_dollars` from `metrics.py`.

## Constraints (`dcf.py`, all pure functions)

1. **Owner earnings** = OCF − |capex| per year (full capex as conservative
   maintenance proxy). Base OE = **min(latest, mean of last 3)** — never
   extrapolate one great year.
2. **Quality gates** → `not_valuable` with the failed reasons listed:
   - fewer than 4 annual periods;
   - latest owner earnings ≤ 0, or OE ≤ 0 in ≥2 of the last 4;
   - OE coefficient of variation (pstdev/|mean| over ≤last 6) > 0.6;
   - diluted/outstanding shares missing or ≤ 0.
3. **Growth, derived then capped:** stage-1 = min(OE CAGR, revenue CAGR, **0.15**),
   floored at **0**; CAGR over the available span (≥3 intervals). Years 1-5 at
   stage-1, years 6-10 **linear fade** to terminal.
4. **Terminal growth** = min(**0.025**, discount − 0.01). **Discount** default
   **0.10** (env `DCF_DISCOUNT_RATE`), hard **floor 0.08**, **+0.02 penalty** when
   debt/equity > 1.
5. **Equity bridge:** PV(10 yearly OE flows) + PV(Gordon terminal:
   OE₁₀·(1+g)/(d−g) discounted 10y) = enterprise value; **− net debt**
   (total_debt − cash); ÷ diluted (fallback outstanding) shares → intrinsic/share.
6. **Margin of safety:** base 0.30; −0.05 if ROIC ≥ 15% in latest year (reuse
   metric); +0.10 if OE CV > 0.35; +0.10 if D/E > 1; **clamp [0.25, 0.50]**.
   `buy_below = intrinsic × (1 − MoS)`.
7. **Sensitivity grid:** 3×3 intrinsic/share over growth {g−0.03 (≥0), g, g+0.03
   (≤0.15)} × discount {0.08, 0.10, 0.12}.
8. **Verdict:** price < buy_below → `undervalued`; ≤ intrinsic → `fair`; else
   `overvalued`; gates failed → `not_valuable`. Response echoes every assumption:
   base OE ($), stage-1 growth, terminal, discount, MoS, net debt, shares, OE CV,
   plus `gate_failures: []` and a disclaimer.

## API + UI
- `DcfResponse` model in `models.py`; route follows the `/outlook` pattern, JWT'd
  via the existing router mount.
- Fundamentals page: "DCF — intrinsic value" card next to Outlook: intrinsic vs
  price, buy-below + MoS, verdict badge, assumptions list, 3×3 sensitivity table,
  gate reasons when `not_valuable`, "—" everywhere a number can't be determined.
  Design-system components + InfoTip explainers.

## Tests (`backend/tests/test_fundamentals_dcf.py`)
Hand-computed two-stage fixture (exact PV equality to ~1e-6), every cap/floor/
gate, erratic-CV refusal, net-debt bridge sign, MoS clamp both ends, sensitivity
shape/monotonicity, router test with mocked series + price.
