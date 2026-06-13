# Evaluator — `fundamentals` DCF (Buffett-grade intrinsic value)

Score each ❌/✅. All ❌ must be fixed before done.

## Formula correctness
- [ ] Owner earnings = OCF − |capex|; base OE = min(latest, 3-yr mean).
- [ ] Two-stage PV verified against a hand-computed fixture (years 1-5 stage-1,
      6-10 linear fade, Gordon terminal discounted 10y) to ≤1e-6 relative error.
- [ ] Equity bridge subtracts net debt (debt − cash) and divides by diluted
      (fallback outstanding) shares; cents→dollars handled once, correctly.

## Constraints enforced (each unit-tested)
- [ ] Stage-1 growth = min(OE CAGR, revenue CAGR, 0.15), floored at 0.
- [ ] Terminal ≤ 0.025 and < discount − 0.01.
- [ ] Discount default 0.10, floor 0.08, +0.02 when D/E > 1.
- [ ] MoS base 0.30 with quality adjustments, clamped [0.25, 0.50];
      buy_below = intrinsic × (1 − MoS).
- [ ] Sensitivity grid is 3×3 over the specified growth/discount sets; intrinsic
      increases with growth and decreases with discount.

## Quality gates (no fabricated numbers)
- [ ] <4 periods, non-positive OE (latest or ≥2 of 4), OE CV > 0.6, missing
      shares → `not_valuable` with the specific reasons; intrinsic fields null.
- [ ] All gate paths unit-tested; API returns 200 with the refusal (not a 500).

## Auditability / safety
- [ ] Response echoes every assumption (base OE, growth, terminal, discount, MoS,
      net debt, shares, OE CV) + disclaimer; deterministic (no randomness/LLM).
- [ ] Route JWT-protected; read-only; strict mypy + ruff clean.

## UI
- [ ] DCF card shows intrinsic vs price, buy-below + MoS%, verdict badge,
      assumptions, 3×3 sensitivity table; `not_valuable` lists gate reasons;
      "—" for indeterminable values; "not financial advice" label present.
