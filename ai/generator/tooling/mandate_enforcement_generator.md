# Generator — Tooling: Rule #1 Mandate Enforcement

**Module:** `tooling` (`scripts/**`)
**Feature:** Source-agnostic enforcement of CLAUDE.md Rule #1
**Primary artifact:** `scripts/check_generator_mandate.py`
**Config:** `ai/mandate.json`

---

## Purpose

Enforce, at the git + CI layer that every change passes through, that no
application code is built without a locked generator + evaluator — regardless
of which tool or human authored it. An instruction file (CLAUDE.md, AGENTS.md)
guides only the tool that reads it; this gate binds all sources equally.

## Build spec

### `ai/mandate.json` (config — single source of truth for scope)
- `modules[]`: each has `name`, `code_globs`, `generator_globs`, `evaluator_globs`.
- `exempt_globs[]`: paths the coverage check ignores (tests, frontend, ai/**,
  config/markup, entrypoint `main.py`).
- Adding/removing a gated area is a config edit here — never a code change.

### `scripts/check_generator_mandate.py` (enforcement engine)

Must implement **two independent checks**:

1. **Lock integrity** — for every entry in `ai/locks/locked.json`, recompute the
   file's SHA-256 and compare to the recorded hash. A mismatch is a violation
   UNLESS the path appears in `ai/locks/unlock_log.json` (key `unlock_events`).
   A locked file missing from disk is also a violation.

2. **Module coverage** — for the set of changed files, skip any matching
   `exempt_globs`; for the rest, find the owning module by `code_globs`. If a
   touched module lacks at least one on-disk generator AND one evaluator
   (per its globs), that is a violation.

### Input modes (mutually exclusive selectors)
- `--staged` — files from `git diff --cached` (pre-commit hook).
- `--all` — entire tree via `git ls-files` (audit).
- default — diff against a merge-base of `--base` (def `origin/main`) and
  `--head` (def `HEAD`); use `git merge-base` so only this branch's changes count.

### Output / contract
- Human-readable, color-coded sections per check.
- Exit `0` on pass, `1` on any violation, `2` on usage/git error.
- On failure, name each offending file and the remedy (`unlock_prompt.sh …`
  for locks; "add generator/evaluator" for coverage).
- Print the source-agnostic reminder on failure.

### Integration points (must stay wired)
- Pre-commit hook `.githooks/pre-commit` calls it with `--staged`.
- CI job `rule1-mandate` in `.github/workflows/pr_checks.yml` calls it with
  `--base origin/<base_ref> --head <pr_head_sha>` and must hard-fail the PR.

## Constraints
- Standard library only (no pip deps) — runs in a bare CI Python.
- Never mutate repo state; read-only.
- Deterministic: same inputs → same verdict.
