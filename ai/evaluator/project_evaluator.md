# Project Evaluator Prompt

**Scope:** Entire Loaded codebase (or a specific module when scoped)
**Version:** 1.1
**Type:** Root-level autonomous evaluator — used by `scripts/robot.py`

---

## Purpose

Score the health of the Loaded project across two axes:

1. **Dimensions** — cross-cutting concerns that apply to every module (security, guardrails, test coverage, completeness)
2. **Modules** — per-module scores, always reported individually regardless of whether the run is full-project or scoped

Every run produces both a per-dimension score and a per-module score. This is true whether the robot runs on the full project or a single module.

---

## How to Run

1. Read `CLAUDE.md` to understand the project architecture
2. Identify all modules: scan `ai/generator/` for subfolders — each is a module
3. For each module found, read its generator prompt and all corresponding source files
4. Read all test files under `backend/tests/`
5. Read prior benchmark results from `ai/benchmarks/results/` (last 3 runs)
6. Score all dimensions AND all modules (see below)
7. Output the full report in the format defined at the bottom

If this is a scoped run (only one module), still score all dimensions — but scope them to that module only. The module scores section will have only that one module.

---

## Dimension Scores (cross-cutting, 0–10 each)

### 1. Security

- [ ] No secrets or API keys hardcoded in any `.py`, `.ts`, `.tsx`, `.json` (excluding `.env*`)
- [ ] No `DEBUG=True` or equivalent in production-facing config
- [ ] CORS `allow_origins=["*"]` — flag as dev-only risk
- [ ] All external API calls use environment variables
- [ ] No `eval()` or `exec()` without sanitization
- [ ] DB writes use parameterized queries (`$1, $2` — not string interpolation)
- [ ] No sensitive data in log statements

Deduct 1.5 per failure.

---

### 2. Guardrails

- [ ] All FastAPI endpoints have Pydantic request validation
- [ ] All Claude API calls have error handlers — no bare `.content[0].text`
- [ ] External data calls (yfinance, Alpaca) have try/except wrappers
- [ ] DB connections closed in finally blocks
- [ ] Frontend API calls show error states — no silent failures
- [ ] No `except: pass` or silent swallowing
- [ ] NL prompt endpoint has input length cap or rate limit guard

Deduct 1.4 per failure.

---

### 3. Unit Test Coverage

For each module that exists, check:
- [ ] Test file exists: `backend/tests/test_{module}_models.py`
- [ ] Test file exists: `backend/tests/test_{module}_generator.py` (if module has a generator)
- [ ] Test file exists: `backend/tests/test_{module}_evaluator.py` (if module has an evaluator)
- [ ] Test file exists: `backend/tests/test_{module}_router.py`
- [ ] At least one negative test per module
- [ ] Tests use fixtures, not hardcoded magic values

Score = (existing test files) / (expected test files) × 10, minus 1 per module missing negative tests.

---

### 4. Integration Test Coverage

- [ ] `backend/tests/test_integration.py` exists
- [ ] At least one full generate → evaluate flow tested
- [ ] At least one DB save + read-back tested
- [ ] DB migration idempotency tested
- [ ] Health endpoint tested (DB connected + disconnected)
- [ ] Frontend e2e tests exist (`frontend/tests/` or `e2e/`)

Score: 2/10 base if no integration tests. +1.6 per passing check above.

---

### 5. Feature Completeness

For each generator prompt in `ai/generator/`:
- [ ] All backend files listed in the generator exist
- [ ] All endpoints listed exist in the router
- [ ] All DB tables listed are in migrations
- [ ] Frontend page exists at the specified path
- [ ] All UI components listed are present

Score = (implemented items) / (total specified items) × 10

---

## Module Scores (per module, 0–10 each)

For each module identified (e.g. `strategies`, `market_data`, `portfolio`):

Score the module on 4 sub-dimensions:

| Sub-dimension | Weight | What to check |
|---|---|---|
| `completeness` | 40% | Generator spec vs actual implementation — every file, endpoint, model, UI component |
| `test_coverage` | 30% | Unit tests exist, cover happy path + edge cases + negative cases |
| `guardrails` | 20% | Error handling, validation, no silent failures within this module |
| `code_quality` | 10% | No dead code, no unused imports, consistent patterns with rest of codebase |

Module overall = (completeness × 0.4) + (test_coverage × 0.3) + (guardrails × 0.2) + (code_quality × 0.1)

---

## Loop Behaviour

Each run:
1. Produces scores for all dimensions AND all modules
2. Identifies the **single lowest scoring item** (dimension or module)
3. Outputs the **single highest-impact next_action** for that item
4. The loop continues until `overall >= target` or `iteration >= max_iterations`

---

## Output Format

Output a JSON block first, then a plain English summary.

```json
{
  "run": {
    "iteration": 1,
    "date": "{date}",
    "scope": "full | {module_name}",
    "evaluator_version": "1.1"
  },
  "scores": {
    "overall": 0.0,
    "dimensions": {
      "security": 0.0,
      "guardrails": 0.0,
      "unit_test_coverage": 0.0,
      "integration_test_coverage": 0.0,
      "feature_completeness": 0.0
    },
    "modules": {
      "{module_name}": {
        "overall": 0.0,
        "completeness": 0.0,
        "test_coverage": 0.0,
        "guardrails": 0.0,
        "code_quality": 0.0
      }
    }
  },
  "delta_from_last_run": {
    "overall": 0.0,
    "dimensions": {},
    "modules": {}
  },
  "failing_checks": [
    {
      "area": "dimension | module",
      "name": "security | strategies | ...",
      "check": "string",
      "file": "string or null",
      "fix": "string — one concrete action"
    }
  ],
  "improvement_suggestions": [
    {
      "what": "string",
      "why": "string",
      "effort": "S|M|L",
      "files": ["string"]
    }
  ],
  "next_action": "string — the single highest-impact fix for this iteration"
}
```

Then output the plain English summary:

```
## Project Health — Iteration {n}  [{scope}]
**Overall: {score}/10**  △ {delta} from last run

### Dimensions
| Dimension              | Score | Delta |
|------------------------|-------|-------|
| Security               | x/10  | +/-x  |
| Guardrails             | x/10  | +/-x  |
| Unit Test Coverage     | x/10  | +/-x  |
| Integration Tests      | x/10  | +/-x  |
| Feature Completeness   | x/10  | +/-x  |

### Modules
| Module      | Overall | Completeness | Tests | Guardrails | Code Quality |
|-------------|---------|--------------|-------|------------|--------------|
| strategies  | x/10    | x/10         | x/10  | x/10       | x/10         |
| ...         | ...     | ...          | ...   | ...        | ...          |

**Next action:** {next_action}
**Suggestions:** {n} improvements identified
```
