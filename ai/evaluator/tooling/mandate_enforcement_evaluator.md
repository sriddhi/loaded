# Evaluator — Tooling: Rule #1 Mandate Enforcement

Checklist for `scripts/check_generator_mandate.py` + `ai/mandate.json`.
Each item is ✅ / ❌. All ❌ must be fixed before the feature is done.

## Config (`ai/mandate.json`)
- [ ] C1. Valid JSON; has `modules` (array) and `exempt_globs` (array).
- [ ] C2. Every module has `name`, `code_globs`, `generator_globs`, `evaluator_globs`.
- [ ] C3. `scripts/**` is gated by a `tooling` module (NOT in `exempt_globs`).
- [ ] C4. Every gated module that exists in the tree has at least one generator
      and one evaluator file on disk matching its globs.

## Lock integrity check
- [ ] L1. Recomputes SHA-256 of each `locked.json` entry and compares to record.
- [ ] L2. Hash mismatch → violation, prints recorded vs actual + remedy.
- [ ] L3. Mismatch is suppressed only if the path is in `unlock_log.json`
      (reads the `unlock_events` key that `unlock_prompt.sh` actually writes).
- [ ] L4. Locked file missing from disk → violation.
- [ ] L5. Against the current tree, the check reports PASS (no tampered locks).

## Module coverage check
- [ ] M1. Files matching `exempt_globs` are skipped.
- [ ] M2. A changed file under a module's `code_globs` requires that module to
      have a generator AND an evaluator; missing either → violation.
- [ ] M3. A new uncovered module (e.g. `backend/app/payments/**` with no prompts)
      is correctly blocked.
- [ ] M4. Frontend, tests, docs, and `main.py` do NOT trigger coverage.

## Input modes & contract
- [ ] I1. `--staged`, `--all`, and default diff modes each select the right files.
- [ ] I2. Default mode uses `git merge-base` (only this branch's changes count).
- [ ] I3. Exit code 0 = pass, 1 = violation, 2 = usage/git error.
- [ ] I4. Standard library only; no network; read-only (no repo mutation).

## Integration
- [ ] G1. `.githooks/pre-commit` invokes the script with `--staged`.
- [ ] G2. CI job `rule1-mandate` invokes it and hard-fails the PR on exit 1.
- [ ] G3. Running `--all` on the repo HEAD after fixes returns exit 0 (green).
