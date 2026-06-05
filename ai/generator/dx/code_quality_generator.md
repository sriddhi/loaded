# Code Quality & DX Generator Prompt

**Feature:** Code Quality, Linting, Type Checks, Formatting, CI, Dev Environment Setup
**Version:** 1.0
**Target:** root config files, `.github/`, `.githooks/`, `.vscode/`, `scripts/setup.sh`

---

## Context

You are adding a complete code quality enforcement system to **Loaded** — an institution-grade trading platform built with FastAPI (Python) + Next.js 14 (TypeScript) + PostgreSQL, running in Docker.

The system must:
1. Enforce quality locally via pre-commit hooks (blocks bad commits)
2. Enforce quality on PRs via GitHub Actions CI (blocks bad PRs)
3. Set up any new contributor's dev environment automatically via one script
4. Bake editor profiles into the repo so VS Code is pre-configured on open

---

## What to Build

### 1. Python tooling config — `pyproject.toml` (repo root)

```toml
[tool.ruff]
target-version = "py311"
line-length = 100
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.11"
strict = false
ignore_missing_imports = true
disallow_untyped_defs = true
warn_return_any = true
warn_unused_ignores = true
exclude = ["backend/tests/"]

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
asyncio_mode = "auto"
```

---

### 2. Frontend tooling config

#### `.eslintrc.json` (repo root)
```json
{
  "extends": ["next/core-web-vitals", "prettier"],
  "rules": {
    "no-unused-vars": "error",
    "no-console": "warn",
    "prefer-const": "error",
    "@typescript-eslint/no-explicit-any": "warn",
    "@typescript-eslint/no-unused-vars": "error"
  }
}
```

#### `.prettierrc` (repo root)
```json
{
  "semi": true,
  "singleQuote": false,
  "tabWidth": 2,
  "trailingComma": "es5",
  "printWidth": 100,
  "bracketSpacing": true
}
```

#### `frontend/.eslintrc.json`
Same as root but scoped to frontend — extend from root config.

---

### 3. Updated pre-commit hook — `.githooks/pre-commit`

Replace the existing hook (which only checks locked files) with a full quality gate. Run checks in this order — fail fast:

```
1. Locked prompt check (existing logic — keep as-is)
2. Python: ruff format check (backend/)
3. Python: ruff lint (backend/)
4. Python: mypy type check (backend/app/)
5. Python: pytest unit tests (backend/tests/, exclude integration)
6. Frontend: prettier format check (frontend/src/)
7. Frontend: eslint (frontend/src/)
8. Frontend: tsc type check (frontend/)
```

Rules:
- Each check prints a clear header: `── Checking: ruff format ──`
- On failure: print the output, print a fix command hint, exit 1
- On pass: print `✅ ruff format`
- Skip frontend checks if no `.ts`/`.tsx` files are staged
- Skip backend checks if no `.py` files are staged
- The locked-file check always runs regardless

Fix hints to print on failure:
- ruff format: `cd backend && ruff format .`
- ruff lint: `cd backend && ruff check . --fix`
- mypy: `cd backend && mypy app/`
- pytest: `cd backend && pytest tests/ -x --ignore=tests/test_integration.py`
- prettier: `cd frontend && npx prettier --write src/`
- eslint: `cd frontend && npx eslint src/ --fix`
- tsc: `cd frontend && npx tsc --noEmit`

---

### 4. GitHub Actions CI — `.github/workflows/pr_checks.yml`

Trigger: `pull_request` targeting `main` or `develop`.

Two parallel jobs:

#### Job: `backend-quality`
- Runs on: `ubuntu-latest`
- Python version: `3.11`
- Steps:
  1. Checkout
  2. Install Python deps: `pip install -r backend/requirements.txt ruff mypy pytest pytest-asyncio`
  3. `ruff format --check backend/`
  4. `ruff check backend/`
  5. `mypy backend/app/ --ignore-missing-imports`
  6. `pytest backend/tests/ -x --ignore=backend/tests/test_integration.py -v`

#### Job: `frontend-quality`
- Runs on: `ubuntu-latest`
- Node version: `20`
- Steps:
  1. Checkout
  2. `npm ci` in `frontend/`
  3. `npx prettier --check frontend/src/`
  4. `npx eslint frontend/src/`
  5. `npx tsc --noEmit` in `frontend/`

Both jobs must pass for the PR to be mergeable. Set as required status checks.

---

### 5. Branch Protection — `scripts/setup_branch_protection.sh`

Script that sets branch protection rules on `main` and `develop` via the GitHub CLI. Run once after repo setup.

```bash
#!/usr/bin/env bash
# Sets GitHub branch protection rules — no merge to main/develop without passing CI

set -euo pipefail

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)

for BRANCH in main develop; do
  echo "Setting protection on: $BRANCH"
  gh api \
    --method PUT \
    "repos/$REPO/branches/$BRANCH/protection" \
    --input - <<EOF
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["backend-quality", "frontend-quality"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false
}
EOF
  echo "✅ Protection set on $BRANCH"
done

echo ""
echo "🔒 Branch protection active:"
echo "   - PRs to main/develop require passing: backend-quality, frontend-quality"
echo "   - Force pushes blocked"
echo "   - Direct commits to main/develop blocked"
```

Rules enforced:
- `required_status_checks.strict = true` — branch must be up to date before merge
- `contexts` — exactly matches the CI job names (`backend-quality`, `frontend-quality`)
- `enforce_admins = true` — applies to repo admins too, no bypassing
- `allow_force_pushes = false` — no force pushing to protected branches
- Direct commits to `main` or `develop` are blocked — PRs only

Also add to `scripts/setup.sh` at the end:
```bash
# 6. Branch protection (requires gh auth)
if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
  ./scripts/setup_branch_protection.sh
else
  echo "ℹ️  Skipping branch protection — run: gh auth login, then ./scripts/setup_branch_protection.sh"
fi
```

---

### 5. Dev environment setup — `scripts/setup.sh`

One script that sets up everything for a new contributor. Must be idempotent (safe to run multiple times).

```bash
#!/usr/bin/env bash
# Loaded — Dev Environment Setup
# Run once after cloning: ./scripts/setup.sh

set -euo pipefail

# 1. Git hooks
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
echo "✅ Git hooks configured"

# 2. Python tooling (backend)
cd backend
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt
pip install -q ruff mypy pytest pytest-asyncio
echo "✅ Python tooling installed (ruff, mypy, pytest)"
cd ..

# 3. Frontend deps
cd frontend
npm ci --silent
echo "✅ Frontend dependencies installed"
cd ..

# 4. Environment file
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "✅ .env created from .env.example — add your API keys"
else
  echo "ℹ️  .env already exists — skipping"
fi

# 5. VS Code extensions (prompt, not force)
if command -v code &>/dev/null; then
  code --install-extension ms-python.python --force 2>/dev/null
  code --install-extension charliermarsh.ruff --force 2>/dev/null
  code --install-extension ms-python.mypy-type-checker --force 2>/dev/null
  code --install-extension esbenp.prettier-vscode --force 2>/dev/null
  code --install-extension dbaeumer.vscode-eslint --force 2>/dev/null
  echo "✅ VS Code extensions installed"
fi

echo ""
echo "🚀 Loaded dev environment ready."
echo "   Fill in .env with your API keys, then: docker compose up -d"
```

---

### 6. VS Code workspace config — `.vscode/settings.json`

```json
{
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true,
    "source.organizeImports": true
  },
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  },
  "[typescript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "[typescriptreact]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "python.linting.enabled": true,
  "mypy-type-checker.enabled": true,
  "ruff.enable": true,
  "ruff.fixAll": true
}
```

#### `.vscode/extensions.json`

```json
{
  "recommendations": [
    "ms-python.python",
    "charliermarsh.ruff",
    "ms-python.mypy-type-checker",
    "esbenp.prettier-vscode",
    "dbaeumer.vscode-eslint",
    "ms-azuretools.vscode-docker",
    "bradlc.vscode-tailwindcss"
  ]
}
```

---

### Renumber: original section 5 (setup.sh) → 6, section 6 (VS Code) → 7

---

## Requirements Checklist

- [ ] `pyproject.toml` exists at repo root with ruff + mypy + pytest config
- [ ] `.eslintrc.json` at repo root extends `next/core-web-vitals` and `prettier`
- [ ] `.prettierrc` at repo root with correct settings
- [ ] Pre-commit hook runs all 8 checks in order, skips irrelevant checks based on staged files
- [ ] Pre-commit hook prints clear pass/fail per check with fix hints on failure
- [ ] Locked-file check still runs first in the hook
- [ ] GitHub Actions workflow triggers on PRs to `main` and `develop`
- [ ] Two parallel CI jobs: `backend-quality` and `frontend-quality`
- [ ] `scripts/setup.sh` is idempotent, sets up hooks + Python + Node + .env + VS Code
- [ ] `.vscode/settings.json` configures format-on-save for Python and TypeScript
- [ ] `.vscode/extensions.json` lists all recommended extensions
- [ ] `eslint-config-prettier` added to frontend deps to resolve prettier/eslint conflicts
- [ ] `@typescript-eslint/eslint-plugin` and `@typescript-eslint/parser` added to frontend devDeps

## What NOT to Do

- Do not remove the locked-file check from the pre-commit hook
- Do not use `--no-verify` anywhere in docs or scripts
- Do not run integration tests in the pre-commit hook (too slow) — unit tests only
- Do not install global packages — all tooling should be project-local
- Do not add `husky` or `lint-staged` — we use our own `.githooks/` system
- Do not add type: ignore comments to pass mypy — fix the types properly
