# Evaluator — `screener` scoring engine + API

Score each ❌/✅. All ❌ fixed before done.

- [ ] Determinism: identical SymbolInputs → byte-identical score dict
      (unit-tested twice over the same fixture).
- [ ] Every pillar tolerates missing inputs alone and all-missing (returns
      None, never raises); composite renormalizes weights; coverage correct.
- [ ] Label ladder exact (unit-tested at boundaries): strong_buy gate
      (≥75 ∧ cov≥.8 ∧ value≥60 ∧ quality≥60), buy ≥60, sell <40 (cov≥.6),
      strong_sell <25 (cov≥.8 ∧ value≤40 ∧ quality≤40), coverage<.5 → hold
      with "insufficient data" reason.
- [ ] All scores clamped 0-100; reasons carry concrete numbers; inputs audit
      blob persisted.
- [ ] Rank assigned per score_date (composite DESC NULLS LAST, equity_id tiebreak)
      in one SQL pass; upserts idempotent.
- [ ] Sector tilts only applied to fired alerts; unmapped alert/sector
      contributes 0.
- [ ] API: filters/sort/pagination correct; candidates side logic
      (buy=strong_buy+buy best-first, sell=strong_sell+sell worst-first);
      unknown symbol 404; admin gating on POST run/refresh (403 non-admin,
      409 when already running); disclaimer everywhere.
- [ ] /discover renders ranked table w/ pillar breakdown + reasons expansion +
      empty state before first run; holdings rows show candidate badges.
- [ ] ruff + strict mypy clean; deterministic tests don't hit the network.
