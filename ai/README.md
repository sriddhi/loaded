# AI Prompts — Generator & Evaluator System

Every feature in Loaded is built using a two-prompt system:

## Workflow

```
Plan  →  Generator Prompt  →  Build  →  Evaluator Prompt  →  Check  →  Benchmark
```

1. **Plan** — before any code is written, the feature is fully planned
2. **Generator** — a prompt that instructs Claude to build the feature correctly
3. **Build** — code is written using the generator as the spec
4. **Evaluator** — a prompt that checks the built code meets all requirements
5. **Benchmark** — both prompts are scored for effectiveness over time

## Folder Structure

Mirrors the codebase:

```
ai/
├── generator/          # prompts that build features
│   ├── strategies/
│   ├── market_data/
│   └── ...
├── evaluator/          # prompts that verify features
│   ├── strategies/
│   ├── market_data/
│   └── ...
└── benchmarks/         # effectiveness scores over time
    └── results/
```

## Naming Convention

- Generator: `{feature}_generator.md`
- Evaluator: `{feature}_evaluator.md`
- Benchmark result: `{feature}_{date}.json`

## Benchmark Metrics

| Metric | Description |
|--------|-------------|
| `completeness` | Did the generator cover all planned requirements? (0–10) |
| `correctness` | Did the evaluator catch real bugs vs false positives? (0–10) |
| `precision` | Were generator instructions specific enough to avoid ambiguity? (0–10) |
| `coverage` | Did the evaluator check all edge cases? (0–10) |
