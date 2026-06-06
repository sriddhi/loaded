#!/usr/bin/env bash
# setup_dev.sh — one-command developer onboarding for Loaded
# Usage: ./scripts/setup_dev.sh
#
# Sets up:
#   1. .env from .env.example
#   2. Python virtualenv + dependencies
#   3. Pre-commit hooks
#   4. Claude Code MCP servers (Alpaca + Linear)
#   5. Cursor MCP servers (Alpaca)
#   6. Docker stack (first boot)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

green()  { echo -e "\033[32m✅  $*\033[0m"; }
yellow() { echo -e "\033[33m⚡  $*\033[0m"; }
red()    { echo -e "\033[31m❌  $*\033[0m"; }
header() { echo -e "\n\033[1;34m── $* ──\033[0m"; }

# ── 1. Environment ─────────────────────────────────────────────────────────────
header "Environment"
if [[ ! -f .env ]]; then
  cp .env.example .env
  yellow ".env created from .env.example — fill in your API keys before running the app"
else
  green ".env already exists"
fi

# ── 2. Python virtualenv ────────────────────────────────────────────────────────
header "Python virtualenv"
if [[ ! -d backend/.venv ]]; then
  python3 -m venv backend/.venv
  green "Created backend/.venv"
fi
source backend/.venv/bin/activate
pip install -q -r backend/requirements.txt
green "Backend dependencies installed"

# ── 3. Pre-commit hooks ─────────────────────────────────────────────────────────
header "Pre-commit hooks"
if command -v pre-commit &>/dev/null; then
  pre-commit install
  green "Pre-commit hooks installed"
else
  yellow "pre-commit not found — install with: pip install pre-commit"
fi

# ── 4. Claude Code MCP ─────────────────────────────────────────────────────────
header "Claude Code MCP servers"
if command -v claude &>/dev/null; then
  # Alpaca (local script, sources .env automatically)
  if claude mcp list 2>/dev/null | grep -q "alpaca"; then
    green "Alpaca MCP already registered"
  else
    claude mcp add alpaca -- "$ROOT/scripts/run_alpaca_mcp.sh"
    green "Alpaca MCP registered"
  fi

  # Linear (remote OAuth — engineer must auth once in browser)
  if claude mcp list 2>/dev/null | grep -q "linear"; then
    green "Linear MCP already registered"
  else
    claude mcp add --transport http linear https://mcp.linear.app/mcp
    green "Linear MCP registered — browser will open for OAuth"
  fi
else
  yellow "Claude Code CLI not found — skipping MCP registration"
  yellow "Install from: https://claude.ai/download then re-run this script"
fi

# ── 5. Cursor MCP ──────────────────────────────────────────────────────────────
header "Cursor MCP"
if [[ -f .cursor/mcp.json ]]; then
  green ".cursor/mcp.json already configured (Alpaca)"
else
  yellow ".cursor/mcp.json not found — open Cursor and it will be auto-detected"
fi

# ── 6. Docker first boot ────────────────────────────────────────────────────────
header "Docker"
if command -v docker &>/dev/null; then
  yellow "Building Docker images (first run may take a few minutes)..."
  docker compose build --quiet
  green "Images built"
  echo ""
  echo "  Start the app:   docker compose up -d"
  echo "  View logs:       docker compose logs -f backend"
  echo "  Frontend:        http://localhost:3000"
  echo "  Backend API:     http://localhost:8000"
else
  yellow "Docker not found — install Docker Desktop from https://docker.com"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "\033[1;32m🚀  Setup complete. Next steps:\033[0m"
echo "  1. Fill in your API keys in .env"
echo "     Required: POSTGRES_PASSWORD, JWT_SECRET_KEY, ANTHROPIC_API_KEY"
echo "     Optional: ALPACA_PAPER_API_KEY, ALPACA_PAPER_SECRET_KEY"
echo "  2. docker compose up -d"
echo "  3. Open http://localhost:3000"
echo ""
echo "  Ask the team lead for your ADMIN_EMAIL and ADMIN_PASSWORD."
echo "  See CLAUDE.md for full architecture docs."
