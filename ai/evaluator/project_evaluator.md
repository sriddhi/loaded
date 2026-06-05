# Project Evaluator Prompt

**Scope:** Entire Loaded codebase  
**Version:** 1.0  
**Type:** Root-level autonomous evaluator — runs on every iteration

---

## Purpose

This evaluator scores the **overall health of the Loaded project** across 6 dimensions. It is not feature-specific — it evaluates the codebase as a whole. It runs in a loop (N iterations or until score ≥ Y) and produces a structured JSON report each run so progress is tracked over time.

---

## How to Run

1. Read `CLAUDE.md` to understand the project architecture
2. Read all files under `backend/` and `frontend/src/`
3. Read all existing tests under `backend/tests/`
4. Read `ai/generator/` to understand what has been planned
5. Read `ai/benchmarks/results/` to understand prior scores
6. Run all 6 evaluation dimensions below
7. Output the full report in the format defined at the bottom

---

## Evaluation Dimensions

### 1. Security (0–10)

Check for:
- [ ] No secrets or API keys hardcoded in source files (scan all `.py`, `.ts`, `.tsx`, `.json` — excluding `.env*`)
- [ ] No `DEBUG=True` or equivalent left in production-facing config
- [ ] CORS: `allow_origins=["*"]` is flagged as acceptable for dev but must be noted as a prod risk
- [ ] All external API calls (Alpaca, Anthropic, yfinance) use environment variables, not hardcoded credentials
- [ ] No `eval()`, `exec()`, or dynamic code execution without input sanitization
- [ ] FastAPI endpoints that write to DB use parameterized queries (asyncpg `$1, $2` — not string interpolation)
- [ ] No sensitive data logged (API keys, user data) in `log.error()` / `print()` calls

Scoring: each failed check deducts 1.5 points from 10.

---

### 2. Guardrails (0–10)

Check for:
- [ ] All FastAPI endpoints have Pydantic request validation (no raw `dict` bodies)
- [ ] All Claude API calls have a fallback / error handler — no unguarded `.content[0].text`
- [ ] yfinance / external data calls have timeouts or try/except wrappers
- [ ] DB operations have try/finally to close connections (no leaked connections)
- [ ] Frontend API calls have error states — user is never left with a silent failure
- [ ] No `except: pass` or bare `except Exception` that swallows errors silently
- [ ] Rate limiting or input length cap on the NL prompt endpoint (prevent prompt injection / abuse)

Scoring: each failed check deducts 1.4 points from 10.

---

### 3. Unit Test Coverage (0–10)

Check for each backend module that exists:
- [ ] `backend/tests/test_strategies_models.py` — tests for StrategyConfig, EvalRequest, EvalResult validation
- [ ] `backend/tests/test_strategies_generator.py` — mocked Claude call, invalid JSON handling, schema mismatch
- [ ] `backend/tests/test_strategies_evaluator.py` — backtest with known data, edge cases (no signals, single trade, bad symbol)
- [ ] `backend/tests/test_strategies_router.py` — endpoint tests using FastAPI TestClient
- [ ] Tests use fixtures / factories — not hardcoded magic values
- [ ] At least one negative test per module (invalid input, error path)

Scoring:
- 0 test files → 0/10
- Each missing test file from the list above → -1.5
- Tests exist but no negative cases → -1 per module

---

### 4. Integration Test Coverage (0–10)

Check for:
- [ ] `backend/tests/test_integration.py` or equivalent — tests the full stack flow end-to-end
- [ ] At least one test that hits `/strategies/generate` → `/strategies/evaluate` in sequence
- [ ] At least one test that saves a strategy to DB and reads it back
- [ ] DB migration is tested — tables are created, schema matches models
- [ ] Health endpoint tested with DB connected and disconnected states
- [ ] Frontend: at least one Playwright or Cypress test exists (check `frontend/tests/` or `e2e/`)

Scoring:
- 0 integration tests → 2/10
- Each missing check above → -1.2

---

### 5. Feature Completeness (0–10)

For every generator prompt in `ai/generator/`, check whether the corresponding code exists and is complete:

For each `ai/generator/{module}/{feature}_generator.md`:
- [ ] All backend files listed in the generator exist
- [ ] All endpoints listed in the generator exist in the router
- [ ] All DB tables listed in the generator are created in migrations
- [ ] Frontend page exists at the path defined in the generator
- [ ] All UI components listed in the generator are present

Scoring:
- Read each generator and cross-reference the codebase
- Score = (implemented requirements) / (total requirements) × 10

---

### 6. Improvement Suggestions (not scored — output only)

After scoring, generate a prioritised list of improvements the project **could add** that are:
- Within the existing plan (referenced in generator prompts or CLAUDE.md)
- Technically feasible with the current stack
- Ranked by impact-to-effort ratio

For each suggestion:
- What: one line description
- Why: how it improves the project
- Effort: S / M / L
- Relevant file(s) to modify

---

## Loop Behaviour

This evaluator is designed to run in a loop. Each run:
1. Produces a score report
2. Identifies the **lowest scoring dimension**
3. Outputs **the single highest-impact fix** for that dimension as a concrete action
4. The loop continues until `overall_score >= target` or `iteration >= max_iterations`

The loop runner (`scripts/run_evaluator.py`) passes prior scores into context so the evaluator can show delta per dimension.

---

## Output Format

Output a JSON block followed by a human-readable summary.

```json
{
  "run": {
    "iteration": 1,
    "date": "{date}",
    "evaluator_version": "1.0"
  },
  "scores": {
    "security": 0.0,
    "guardrails": 0.0,
    "unit_test_coverage": 0.0,
    "integration_test_coverage": 0.0,
    "feature_completeness": 0.0,
    "overall": 0.0
  },
  "delta_from_last_run": {
    "security": 0.0,
    "guardrails": 0.0,
    "unit_test_coverage": 0.0,
    "integration_test_coverage": 0.0,
    "feature_completeness": 0.0,
    "overall": 0.0
  },
  "failing_checks": [
    {
      "dimension": "string",
      "check": "string",
      "file": "string or null",
      "fix": "string — concrete single action"
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

Then output a plain English summary:

```
## Project Health — Iteration {n}
**Overall: {score}/10**  △ {delta} from last run

| Dimension              | Score | Delta |
|------------------------|-------|-------|
| Security               | x/10  | +/-x  |
| Guardrails             | x/10  | +/-x  |
| Unit Test Coverage     | x/10  | +/-x  |
| Integration Tests      | x/10  | +/-x  |
| Feature Completeness   | x/10  | +/-x  |

**Next action:** {next_action}
**Suggestions:** {n} improvements identified
```
