# Code Quality & DX Evaluator Prompt

**Feature:** Code Quality, Linting, Type Checks, Formatting, CI, Dev Environment Setup
**Version:** 1.0
**Checks against:** `ai/generator/dx/code_quality_generator.md`

---

## How to Run

1. Read `ai/generator/dx/code_quality_generator.md` fully
2. Read all files listed in the checks below
3. Mark each check ✅ PASS or ❌ FAIL with evidence (file + line or specific issue)
4. Compute scores and output the report

---

## Checks

### Python Config (`pyproject.toml`)

- [ ] File exists at repo root
- [ ] `[tool.ruff]` section present with `target-version`, `line-length`, `select`, `ignore`
- [ ] `[tool.ruff.format]` section present
- [ ] `[tool.mypy]` section present with `disallow_untyped_defs = true` and `warn_return_any = true`
- [ ] `[tool.pytest.ini_options]` section present with `testpaths = ["backend/tests"]`
- [ ] `asyncio_mode = "auto"` set (required for async FastAPI tests)

### Frontend Config

- [ ] `.eslintrc.json` exists at repo root
- [ ] Extends `next/core-web-vitals` and `prettier`
- [ ] `no-unused-vars` set to `error`
- [ ] `@typescript-eslint/no-unused-vars` set to `error`
- [ ] `.prettierrc` exists at repo root
- [ ] `semi: true`, `singleQuote: false`, `printWidth: 100` set
- [ ] `eslint-config-prettier` in `frontend/package.json` devDependencies
- [ ] `@typescript-eslint/eslint-plugin` in `frontend/package.json` devDependencies
- [ ] `@typescript-eslint/parser` in `frontend/package.json` devDependencies

### Pre-commit Hook (`.githooks/pre-commit`)

- [ ] Locked-file check runs FIRST before all other checks
- [ ] Check 2: ruff format check — runs only when `.py` files are staged
- [ ] Check 3: ruff lint — runs only when `.py` files are staged
- [ ] Check 4: mypy type check — runs only when `.py` files are staged
- [ ] Check 5: pytest unit tests — runs only when `.py` files are staged, excludes integration tests
- [ ] Check 6: prettier format check — runs only when `.ts`/`.tsx` files are staged
- [ ] Check 7: eslint — runs only when `.ts`/`.tsx` files are staged
- [ ] Check 8: tsc type check — runs only when `.ts`/`.tsx` files are staged
- [ ] Each check prints a clear header before running
- [ ] Each passing check prints `✅ {check name}`
- [ ] Each failing check prints the tool output AND a fix hint command
- [ ] Exit code 1 on any failure
- [ ] Exit code 0 when all checks pass
- [ ] Hook is executable (`chmod +x` applied)

### GitHub Actions (`.github/workflows/pr_checks.yml`)

- [ ] File exists at `.github/workflows/pr_checks.yml`
- [ ] Triggers on `pull_request` to `main`
- [ ] Triggers on `pull_request` to `develop`
- [ ] Job `backend-quality` exists
- [ ] `backend-quality` uses `ubuntu-latest` and Python `3.11`
- [ ] `backend-quality` runs: ruff format check, ruff lint, mypy, pytest (no integration tests)
- [ ] Job `frontend-quality` exists
- [ ] `frontend-quality` uses `ubuntu-latest` and Node `20`
- [ ] `frontend-quality` runs: prettier check, eslint, tsc
- [ ] Both jobs run in parallel (not sequential)
- [ ] Workflow has a clear name (shown in GitHub PR checks UI)

### Dev Setup Script (`scripts/setup.sh`)

- [ ] File exists and is executable
- [ ] Sets `git config core.hooksPath .githooks`
- [ ] Makes `.githooks/pre-commit` executable
- [ ] Creates Python venv in `backend/.venv`
- [ ] Installs `requirements.txt` + `ruff mypy pytest pytest-asyncio`
- [ ] Runs `npm ci` in `frontend/`
- [ ] Copies `.env.example` to `.env` only if `.env` doesn't already exist (idempotent)
- [ ] Installs VS Code extensions if `code` CLI is available
- [ ] Script is idempotent — safe to run multiple times without errors
- [ ] Clear success messages printed at each step

### VS Code Config (`.vscode/`)

- [ ] `.vscode/settings.json` exists
- [ ] `editor.formatOnSave: true` set
- [ ] Python formatter set to `charliermarsh.ruff`
- [ ] TypeScript/TSX formatter set to `esbenp.prettier-vscode`
- [ ] `mypy-type-checker.enabled: true` set
- [ ] `ruff.fixAll: true` set
- [ ] `.vscode/extensions.json` exists
- [ ] Recommends: `ms-python.python`, `charliermarsh.ruff`, `ms-python.mypy-type-checker`, `esbenp.prettier-vscode`, `dbaeumer.vscode-eslint`

### Branch Protection (`scripts/setup_branch_protection.sh`)

- [ ] File exists and is executable
- [ ] Uses `gh api PUT repos/{repo}/branches/{branch}/protection`
- [ ] Applies to both `main` and `develop` branches
- [ ] `required_status_checks.contexts` includes `backend-quality` and `frontend-quality` — exact job names matching CI
- [ ] `required_status_checks.strict = true` — branch must be up to date before merge
- [ ] `enforce_admins = true` — no bypass for repo admins
- [ ] `allow_force_pushes = false`
- [ ] `setup.sh` calls `setup_branch_protection.sh` if `gh` is authenticated, else prints skip message

### End-to-End Checks

- [ ] Running `./scripts/setup.sh` completes without errors on a clean clone
- [ ] Staging a `.py` file with a lint error and committing is blocked by the hook
- [ ] Staging a `.tsx` file with a prettier violation and committing is blocked
- [ ] Staging only a markdown file skips all Python and frontend checks
- [ ] Staging a locked prompt file is still blocked (existing behavior preserved)
- [ ] Pushing a PR to `main` triggers both CI jobs in GitHub Actions
- [ ] A PR with a mypy error fails CI
- [ ] A PR with a clean codebase passes all CI checks
- [ ] A direct push to `main` is rejected by GitHub branch protection
- [ ] A PR with failing CI cannot be merged — merge button disabled on GitHub

---

## Scoring

```
config_score      = (pyproject + eslint + prettier checks passed) / total × 10
hook_score        = (pre-commit checks passed) / total × 10
ci_score          = (github actions checks passed) / total × 10
protection_score  = (branch protection checks passed) / total × 10
setup_score       = (setup.sh checks passed) / total × 10
vscode_score      = (vscode checks passed) / total × 10
e2e_score         = (e2e checks passed) / total × 10

overall = (config_score + hook_score + ci_score + protection_score + setup_score + vscode_score + e2e_score) / 7
```

---

## Output Format

```
## Evaluation Report — Code Quality & DX
**Date:** {date}
**Overall Score:** {score}/10

### ✅ Passing ({n})
- list

### ❌ Failing ({n})
- Check: {name}
  File: {path}
  Issue: {what's wrong}
  Fix: {one concrete action}

### Score Breakdown
| Area            | Score |
|-----------------|-------|
| Config          | x/10  |
| Pre-commit hook | x/10  |
| CI              | x/10  |
| Setup script    | x/10  |
| VS Code         | x/10  |
| End-to-end      | x/10  |
| **Overall**     | x/10  |
```
