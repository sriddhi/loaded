# AI — Generator & Evaluator System

This is the project-wide build system for Loaded. It operates in two distinct modes.

---

## Mode 1 — Build Mode (human in the loop)

**Triggered when:** planning or building any feature.

```
Plan  →  Generator Prompt  →  Finalize + Lock  →  Build  →  Evaluator Prompt  →  Check  →  Benchmark
```

1. **Plan** — feature is fully designed in conversation before touching code
2. **Generator** — Claude writes `ai/generator/{module}/{feature}_generator.md` — the full build spec
3. **Evaluator** — Claude writes `ai/evaluator/{module}/{feature}_evaluator.md` — the verification checklist
4. **Finalize** — user confirms both prompts; they are locked via `./scripts/lock_prompt.sh`
5. **Build** — code is written using the generator as the single source of truth
6. **Check** — evaluator prompt is run against the built code; score reported
7. **Benchmark** — result saved to `ai/benchmarks/results/{feature}_{date}.json`

**Rules:**
- No code is written before generator + evaluator exist and are confirmed
- Locked prompts cannot be modified during build or test (`git pre-commit` enforces this)
- To unlock: `./scripts/unlock_prompt.sh <file> "<reason>"` — logs the event

---

## Mode 2 — Robot Mode (autonomous)

**Triggered when:** user says *"run the robot"*.

```bash
python scripts/robot.py                               # full project, 3 iterations, target 9.0
python scripts/robot.py --module strategies           # only the strategies module
python scripts/robot.py --module strategies --until 9.5
python scripts/robot.py --iterations 10 --until 9.0
python scripts/robot.py --list-modules                # show available modules
python scripts/robot.py --dry-run                     # preview prompt only
```

The robot:
1. Reads the entire codebase
2. Runs `ai/evaluator/project_evaluator.md` — scores 6 dimensions of project health
3. Saves a result to `ai/benchmarks/results/project_health_{date}_iter{n}.json`
4. Shows delta from the previous run
5. Outputs the single highest-impact `next_action`
6. Loops until score ≥ target OR max iterations reached

**Robot does not ask for confirmation mid-run.** It scores, saves, and continues.

---

## Two Evaluator Types

| | Feature Evaluator | Project Evaluator |
|---|---|---|
| **Scope** | One feature | Entire codebase |
| **Triggered by** | End of a feature build | `run the robot` |
| **Checks** | Completeness vs generator spec | Security, guardrails, tests, completeness |
| **Output** | Pass/fail per requirement | Score per dimension + delta + next action |
| **Location** | `ai/evaluator/{module}/{feature}_evaluator.md` | `ai/evaluator/project_evaluator.md` |
| **Loop** | No — run once after build | Yes — N iterations or until score ≥ Y |

---

## Folder Structure

Mirrors the codebase exactly.

```
ai/
├── generator/                  # build specs (one per feature)
│   ├── strategies/
│   ├── market_data/
│   ├── portfolio/
│   └── ...
├── evaluator/                  # verification prompts
│   ├── project_evaluator.md   ← root-level, used by robot
│   ├── strategies/
│   ├── market_data/
│   └── ...
├── locks/
│   ├── locked.json            ← manifest of finalized prompts
│   └── unlock_log.json        ← audit trail
└── benchmarks/
    └── results/               ← all benchmark outputs
```

---

## File Naming

| File | Pattern |
|------|---------|
| Feature generator | `ai/generator/{module}/{feature}_generator.md` |
| Feature evaluator | `ai/evaluator/{module}/{feature}_evaluator.md` |
| Project evaluator | `ai/evaluator/project_evaluator.md` |
| Feature benchmark | `ai/benchmarks/results/{feature}_{date}.json` |
| Robot benchmark | `ai/benchmarks/results/project_health_{date}_iter{n}.json` |

---

## Benchmark Metrics

### Feature evaluator
| Metric | Description |
|--------|-------------|
| `completeness` | Did the generator cover all planned requirements? |
| `ui_coverage` | Were all frontend components built as specified? |
| `e2e_coverage` | Do end-to-end flows work? |

### Project evaluator (robot)
| Dimension | Description |
|-----------|-------------|
| `security` | No secrets, safe queries, no exposed credentials |
| `guardrails` | Validation, error handling, no silent failures |
| `unit_test_coverage` | Per-module tests with negative cases |
| `integration_test_coverage` | Full stack flows, DB round-trips |
| `feature_completeness` | All generator specs fully implemented |

Target: **9.0+ overall** for both.
