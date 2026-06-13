# Evaluator — `portfolio` BUILD + INSIGHTS

Score each ❌/✅. All ❌ fixed before done.

- [ ] Every health check fires at its documented threshold (boundary
      unit-tests: 10/20% position, +10/+20pts sector, 5/10 breadth, HHI bands,
      20% cash, 25% sell-ranked value).
- [ ] Diversification score bounded 0-100; empty portfolio → 0; component
      weights as documented.
- [ ] Suggestions: 10% position cap enforced; score_weighted only proposes
      buy/strong_buy not already held; equal_weight tops up underweights;
      sub-0.1-share suggestions skipped; never suggests with zero cash.
- [ ] Insights composition: empty scores / no fired alerts / no earnings →
      empty sections with sane summaries, never an exception; macro impacts
      only include alerts touching held sectors; weight math = sector weights
      of current holdings.
- [ ] meaning/impact text comes from the macro ALERT_INFO registry (no
      duplicated copy); fired_since passed through.
- [ ] Endpoints owner-scoped (404 cross-user), JWT'd, disclaimer on every
      response; suggestions labeled educational illustration.
- [ ] Insights tab renders all sections incl. empty states; no broken UI.
- [ ] ruff + strict mypy clean (both invocations); tests per app file.
