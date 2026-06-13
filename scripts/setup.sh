#!/usr/bin/env bash
# Loaded — Dev Environment Setup
# Run once after cloning: ./scripts/setup.sh
# Safe to run multiple times (idempotent).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ""
echo "🚀 Setting up Loaded dev environment..."
echo ""

# ── 1. Git hooks ──────────────────────────────────────────────────────────────
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
echo "✅ Git hooks configured (.githooks/pre-commit)"

# ── 2. Python tooling ─────────────────────────────────────────────────────────
echo ""
echo "Setting up Python (backend)..."
cd "$ROOT/backend"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
  echo "   Created .venv"
fi

source .venv/bin/activate
pip install -q -r requirements.txt
pip install -q ruff mypy pytest pytest-asyncio
echo "✅ Python tooling installed (ruff, mypy, pytest, pytest-asyncio)"
cd "$ROOT"

# ── 3. Frontend deps ──────────────────────────────────────────────────────────
echo ""
echo "Setting up frontend (Node)..."
cd "$ROOT/frontend"
npm ci --silent
echo "✅ Frontend dependencies installed"
cd "$ROOT"

# ── 4. Environment file ───────────────────────────────────────────────────────
echo ""
if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "✅ .env created from .env.example"
  echo "   ⚠️  Add your API keys to .env before running the stack"
else
  echo "ℹ️  .env already exists — skipping"
fi

# ── 5. VS Code extensions ─────────────────────────────────────────────────────
echo ""
if command -v code &>/dev/null; then
  echo "Installing VS Code extensions..."
  code --install-extension ms-python.python --force       2>/dev/null && echo "   ✅ ms-python.python"
  code --install-extension charliermarsh.ruff --force     2>/dev/null && echo "   ✅ charliermarsh.ruff"
  code --install-extension ms-python.mypy-type-checker --force 2>/dev/null && echo "   ✅ ms-python.mypy-type-checker"
  code --install-extension esbenp.prettier-vscode --force 2>/dev/null && echo "   ✅ esbenp.prettier-vscode"
  code --install-extension dbaeumer.vscode-eslint --force 2>/dev/null && echo "   ✅ dbaeumer.vscode-eslint"
  code --install-extension ms-azuretools.vscode-docker --force 2>/dev/null && echo "   ✅ ms-azuretools.vscode-docker"
else
  echo "ℹ️  VS Code CLI not found — open VS Code manually to install recommended extensions"
fi

# ── 6. Branch protection ──────────────────────────────────────────────────────
echo ""
if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
  "$ROOT/scripts/setup_branch_protection.sh"
else
  echo "ℹ️  Skipping branch protection (gh not authenticated)"
  echo "   Run: gh auth login, then ./scripts/setup_branch_protection.sh"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Loaded dev environment ready."
echo ""
echo "   Next steps:"
echo "   1. Fill in .env with your API keys"
echo "   2. docker compose up -d"
echo "   3. http://localhost:4000"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
