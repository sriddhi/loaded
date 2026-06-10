# GitHub Copilot instructions — pointer to the canonical mandate

This repo enforces a NON-NEGOTIABLE generator+evaluator system (Rule #1) for
ALL code, regardless of which tool wrote it.

**Read and follow `AGENTS.md`** (and `CLAUDE.md` for the full reference).

## Rule #1 (summary)

Before writing or modifying code under `backend/app/{module}/`:

1. Finalize design in chat — no code yet.
2. Write `ai/generator/{module}/{feature}_generator.md`.
3. Write `ai/evaluator/{module}/{feature}_evaluator.md`.
4. Lock both: `./scripts/lock_prompt.sh <file>`.
5. Build from the generator spec.
6. Run the evaluator; fix all failures.

## This is enforced, not advisory

- Pre-commit hook: `.githooks/pre-commit`
- CI hard gate: `.github/workflows/pr_checks.yml` → job `rule1-mandate`
- Logic: `scripts/check_generator_mandate.py` (config `ai/mandate.json`)

A PR that touches a module with no generator+evaluator, or that modifies a
locked prompt without an unlock-log entry, **cannot be merged**. Author the
prompts first rather than working around the gate.
