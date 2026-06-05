# Benchmarks

Tracks effectiveness of generator and evaluator prompts over time.

## Structure

```
benchmarks/
└── results/
    └── strategies_2026-06-05.json    # one file per feature per run
```

## Result Schema

```json
{
  "feature": "strategies",
  "date": "2026-06-05",
  "generator_version": "1.0",
  "evaluator_version": "1.0",
  "scores": {
    "completeness": 8.5,
    "ui_coverage": 9.0,
    "e2e_coverage": 7.0,
    "overall": 8.2
  },
  "failing_checks": 4,
  "total_checks": 38,
  "notes": "Equity curve edge case missed, DB migration not idempotent"
}
```

## How to Benchmark

1. Build the feature using the generator prompt
2. Run the evaluator prompt — get the score report
3. Save result as `results/{feature}_{date}.json`
4. If overall < 8.0: iterate on the generator or evaluator prompt, increment version, re-run

## Goal

Both generator and evaluator should reach **9.0+ overall** within 3 iterations.
