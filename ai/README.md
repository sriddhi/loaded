# AI — Generator & Evaluator System

This is the project-wide build system for Loaded. **Every feature built in this project must have a generator and evaluator prompt before any code is written.**

---

## Workflow

```
Plan  →  Generator Prompt  →  Build  →  Evaluator Prompt  →  Check  →  Benchmark
```

1. **Plan** — feature is fully designed before touching code
2. **Generator** — a prompt that gives Claude the full spec to build the feature correctly
3. **Build** — code is written using the generator as the single source of truth
4. **Evaluator** — a prompt that audits the built code against every requirement
5. **Benchmark** — both prompts are scored; iterate until overall ≥ 9.0

---

## Folder Structure

Mirrors the codebase exactly. Every module in `backend/` or `frontend/` has a corresponding folder here.

```
ai/
├── generator/                  # build specs
│   ├── strategies/
│   ├── market_data/
│   ├── portfolio/
│   ├── alerts/
│   ├── auth/
│   └── ...                     # one folder per backend/frontend module
├── evaluator/                  # verification checklists
│   ├── strategies/
│   ├── market_data/
│   ├── portfolio/
│   ├── alerts/
│   ├── auth/
│   └── ...
└── benchmarks/
    ├── README.md
    └── results/                # {feature}_{date}.json
```

---

## File Naming

| File | Pattern |
|------|---------|
| Generator | `ai/generator/{module}/{feature}_generator.md` |
| Evaluator | `ai/evaluator/{module}/{feature}_evaluator.md` |
| Benchmark | `ai/benchmarks/results/{feature}_{date}.json` |

---

## What Goes in a Generator

- Full stack context (backend paths, frontend paths, design system)
- Exact file and folder structure to create
- Every model, endpoint, component, and DB change required
- Edge cases and error handling expectations
- Explicit "What NOT to Do" section
- Requirements checklist at the bottom

## What Goes in an Evaluator

- Reads the corresponding generator as the source of truth
- One check per requirement (granular — not "does auth work" but "does `/auth/login` return 401 on wrong password")
- Covers: backend logic, API contracts, frontend UI, edge cases, end-to-end flows
- Scoring formula: completeness + ui_coverage + e2e_coverage → overall /10
- Structured output format for saving as benchmark result

---

## Benchmark Metrics

| Metric | Description |
|--------|-------------|
| `completeness` | Did the generator cover all planned requirements? (0–10) |
| `correctness` | Did the evaluator catch real bugs vs false positives? (0–10) |
| `precision` | Were generator instructions specific enough to avoid ambiguity? (0–10) |
| `coverage` | Did the evaluator check all edge cases? (0–10) |

Target: **9.0+ overall within 3 iterations** per feature.
