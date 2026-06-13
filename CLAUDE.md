# CLAUDE.md

This file is the single source of truth for how Claude operates in this repository. Read it fully before doing anything.

---

## Rule #1 — Generator & Evaluator System (NON-NEGOTIABLE)

**Every piece of code built in this repo follows this system. No exceptions.**

This applies to:
- New features
- New endpoints or routes
- New frontend pages or components
- Refactors of existing modules
- Bug fixes that touch more than one file
- Any Claude Code session that involves writing or modifying code

### Mode 1 — Build Mode

Triggered when: planning or building anything.

```
Plan → Generator Prompt → Evaluator Prompt → Confirm + Lock → Build → Evaluate → Benchmark
```

**Step by step:**
1. Discuss and finalize the feature design in conversation — no code yet
2. Claude writes `ai/generator/{module}/{feature}_generator.md` — the full build spec
3. Claude writes `ai/evaluator/{module}/{feature}_evaluator.md` — the verification checklist
4. User confirms both. Claude locks them: `./scripts/lock_prompt.sh <file>`
5. Claude builds the feature using the generator as the only spec
6. Claude runs the evaluator against the built code and reports the score
7. All ❌ failures are fixed before the feature is considered done
8. Score saved to `ai/benchmarks/results/{feature}_{date}.json`

**Hard rules:**
- No code is written before step 4 (confirmation + lock)
- Locked prompt files cannot be committed with changes — the git pre-commit hook blocks it
- To unlock: `./scripts/unlock_prompt.sh <file> "<reason>"` — reason is logged permanently
- Generator and evaluator for the same feature must always be in sync

### Mode 2 — Robot Mode

Triggered when: user says **"run the robot"**.

```bash
python3 scripts/robot.py                               # full project, 3 iterations, target 9.0
python3 scripts/robot.py --module strategies           # single module only
python3 scripts/robot.py --iterations 10 --until 9.5  # custom loop
python3 scripts/robot.py --list-modules                # see available modules
python3 scripts/robot.py --dry-run                     # preview prompt, no API call
```

The robot runs `ai/evaluator/project_evaluator.md` autonomously. It scores two axes every run:
- **Dimensions:** security, guardrails, unit tests, integration tests, feature completeness
- **Modules:** per-module scores (completeness, test coverage, guardrails, code quality)

It loops until overall score ≥ target or max iterations reached. Do not interrupt mid-run. Results saved to `ai/benchmarks/results/`.

### What never changes
- No code without a generator + evaluator
- Locked prompts are immutable during build/test
- Benchmark results are never deleted
- See `ai/README.md` for full reference

---

## Engineer Onboarding

New to the team? One command gets you fully set up:

```bash
./scripts/setup_dev.sh
```

This script:
1. Creates `.env` from `.env.example`
2. Sets up the Python virtualenv + installs all backend dependencies
3. Installs pre-commit hooks (ruff, mypy, pytest — same as CI)
4. Registers **Alpaca MCP** in Claude Code (market data + trading tools available as `/` commands)
5. Registers **Linear MCP** in Claude Code (issue tracking — OAuth browser flow opens once)
6. Builds Docker images on first boot

After running, fill in your API keys in `.env` (get them from the team lead), then:

```bash
docker compose up -d
# → Frontend: http://localhost:4000
# → Backend API: http://localhost:9000
```

### Developer Tools Included

| Tool | Purpose | How it loads |
|---|---|---|
| **Claude Code** | AI pair programmer, knows this codebase | `.claude/settings.json` + `.claude/mcp.json` |
| **Alpaca MCP** | Live market data + trading tools in Claude | Auto-registered by `setup_dev.sh` |
| **Linear MCP** | Issue tracking in Claude (read + create issues) | Auth once in browser via `setup_dev.sh` |
| **Cursor** | IDE with Alpaca MCP pre-wired | `.cursor/mcp.json` (auto-detected) |
| **Pre-commit** | Runs ruff, mypy, pytest before every commit | Installed by `setup_dev.sh` |

### MCP Tools Available After Setup

Once registered, Claude Code can:
- Pull your **Linear issues** and create new ones directly from the conversation
- Query **live market data** via Alpaca (quotes, positions, orders, news)
- Place **paper trades** for strategy testing

### Getting API Keys

Contact the team lead for:
- `JWT_SECRET_KEY` — generate your own: `openssl rand -hex 32`
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — ask team lead for your account
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com)
- `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_SECRET_KEY` — from [app.alpaca.markets/paper](https://app.alpaca.markets/paper/dashboard/overview)

---

## What is Loaded

Loaded is the enterprise-grade evolution of the Vertex trading strategy POC. It is a dockerized full-stack web application targeting both GenZ traders and seasoned professionals — minimal, clean, data-first design.

---

## Running the Stack

Everything runs in Docker. There is no local dev server outside of containers.

```bash
# Start all services (postgres, backend, frontend)
docker compose up -d

# Stop all services
docker compose down

# Rebuild after code changes
docker compose build
docker compose up -d

# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Rebuild a single service
docker compose build backend && docker compose up -d backend
```

Services:
- `http://localhost:4000` — Next.js frontend
- `http://localhost:9000` — FastAPI backend
- PostgreSQL runs internally only (no exposed port)

**Port convention:** loaded uses host ports in the **9000–9999** range for the
API/backend and **4000–4999** for the frontend — never the common 3000/8000
defaults (avoids collisions with other local projects). Host ports are
overridable via `BACKEND_PORT` (default 9000) and `FRONTEND_PORT` (default 4000).
Postgres (5432) and Redis (6379) keep their standard ports but are internal-only
(never published to the host). New host-facing services should claim ports from
these ranges unless a specific port is required.

---

## Architecture

```
loaded/
├── frontend/          Next.js 14 (TypeScript, standalone output)
│   └── src/
│       ├── app/       App Router pages + global styles
│       └── components/
├── backend/
│   └── app/
│       ├── main.py           FastAPI entry point + DB migrations
│       └── strategies/       Strategy Generator + Evaluator module
├── ai/                       Generator & Evaluator prompt system
│   ├── generator/            Build specs (one per feature)
│   ├── evaluator/            Verification checklists + project_evaluator.md
│   ├── locks/                Locked prompt manifest + unlock audit log
│   └── benchmarks/results/   All benchmark outputs
├── scripts/
│   ├── robot.py              Autonomous evaluator loop runner
│   ├── lock_prompt.sh        Lock a finalized prompt
│   └── unlock_prompt.sh      Unlock with mandatory reason
├── docker-compose.yml
└── .env.example
```

**Data flow:** Frontend polls `NEXT_PUBLIC_API_URL/health` every 30 seconds. The backend checks PostgreSQL connectivity on each health request via `asyncpg`. Health also reports Alpaca API connectivity when credentials are configured.

**Alpaca MCP:** Cursor loads `.cursor/mcp.json`, which runs `scripts/run_alpaca_mcp.sh` (sources `.env`, then `uvx alpaca-mcp-server`). Paper trading is the default.

**Networking:** All containers share `loaded_net` bridge network. Service-to-service DNS uses container service names (`postgres`, `backend`, `frontend`). PostgreSQL has no exposed host port — only reachable from within the Docker network.

**Frontend build:** Uses `output: "standalone"` in `next.config.mjs` — the Docker image copies `.next/standalone` and runs `node server.js` directly (no `next start`).

---

## Environment

Copy `.env.example` to `.env` before first run:
```bash
cp .env.example .env
```

Key variables:
- `POSTGRES_PASSWORD` — shared by compose and backend `DATABASE_URL`
- `NEXT_PUBLIC_API_URL` — set to `http://localhost:9000` for local dev
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — Alpaca paper trading keys
- `ALPACA_PAPER_TRADE` — defaults to `true`; set `false` for live trading
- `ANTHROPIC_API_KEY` — required for strategy generator and robot

---

## Alpaca MCP & Connectivity Tests

```bash
# Config + MCP package checks (no API keys required for first 3 tests)
cd backend && pytest tests/test_alpaca_connectivity.py -v

# Full API connectivity (requires keys in .env)
cd backend && pytest tests/test_alpaca_connectivity.py -v -k api_connectivity
```

---

## Backend

FastAPI with `asyncpg` (raw PostgreSQL, no ORM). New endpoints go in new router files under `backend/app/{module}/router.py`, imported in `main.py`. After changes:

```bash
docker compose build backend && docker compose up -d backend
```

---

## Frontend

Next.js 14 App Router. Components in `src/components/`, pages in `src/app/`. After changes:

```bash
docker compose build frontend && docker compose up -d frontend
```

`NEXT_PUBLIC_*` env vars are baked in at build time — changing them requires a rebuild.

---

## Design Principles

**Design system: monochrome + one accent.** Tokens live in
`frontend/src/theme/tokens.ts` (mirrored as CSS vars in `app/globals.css`);
shared primitives in `frontend/src/components/ui/` (`PageShell`, `Card`,
`Button`, `Badge`, `Stat`, `Tabs`, `InfoTip`, `Chart`). New UI composes these,
not ad-hoc hex.

- Monochrome surfaces: bg `#0e0e0e`, surface `#171717` / `#1e1e1e`, border `#2a2a2a`
- Near-white primary `#e5e5e5`; a single restrained accent hue — electric blue
  `#4f9dff` — used sparingly (links, key actions, primary chart series)
- Muted data states: up `#46a758` · down `#e5484d` · warn `#d9a441` (not neon)
- Monospace for all data/status text (`SF Mono`, `Fira Code`, `Cascadia Code`)
- Charts via the shared `Chart` wrapper (`chartPalette`); pages are mobile-first
  (`useIsMobile` + `MOBILE_BREAKPOINT`) so a future mobile build reuses the same
  primitives. No broken/placeholder screens.
- No unnecessary UI — every element earns its place
- Audience: GenZ traders who value speed + simplicity, and seasoned traders who value data density

## Feature surfaces (current)

- **Signals** (`/signals`): per-symbol (SPY/MU/AVGO) volume-aware heuristic over
  1m/5m/10m/20m/1d, each backtested (hit-rate + avg confidence) with an RSI 0-100
  oversold→overbought oscillator. Indicator only — not advice.
- **Fundamentals** (`/fundamentals`): statements + on-demand metrics (REST price
  fallback), any-metric comparative charts, a deterministic technical summary,
  **forward P/E** (`/forward`), and **outlook** (`/outlook`): heuristic fair value +
  buy/sell/neutral with confidence for 1d/1w/1mo/1y/3y/5y + growth/value tags.
- **Strategy Lab** (`/strategies`): chat (market-aware, tool-using) + dynamic
  artifact panel; save strategies with per-strategy mode (backtest/signal/paper),
  schedule (manual/once/interval/daily), and run history. Paper mode is
  hard-gated to the Alpaca **paper** account.
- **Discover** (`/discover`): nightly composite scoring of the S&P 500 +
  Nasdaq-100 (~516 names) — value (DCF + sector P/E), quality, growth,
  momentum, analyst, macro-fit pillars → ranked strong_buy…strong_sell
  candidates with per-pillar breakdowns and reasons. Coverage-gated labels
  (insufficient data → hold). `/screener/*` API; admin manual run.
- **Portfolio** (`/portfolio`): per-user books & records — manual portfolios
  (transactions → derived avg-cost holdings, realized/unrealized P&L) and a
  read-only Alpaca-paper synced portfolio; EOD snapshots, daily-chained TWR +
  beta, allocation/concentration; health checks + diversification score +
  sizing suggestions; insights (holdings × screener scores × fired macro
  alerts × upcoming earnings); daily-cached AI advisor commentary via the
  strategy-chat provider. Never places orders. Not financial advice.
- **Macro** (`/macro`): FRED-sourced trackers (CPI vs Fed funds / wage income /
  2Y, PPI headline-vs-core, CPI−PPI spread, claims, ECB+bunds) with the SVM
  alert playbook (11 FRED rules + SPY/IGV/SMH moving-average technicals).
  Series auto-refresh hourly by frequency TTL (daily 6h / weekly 12h / monthly
  24h); works keyless via fredgraph.csv, upgrades to the official API when
  `FRED_API_KEY` is set. Informational only — not financial advice.
- **Tools** (`/tools`): live job status + API latency/error metrics.
- **Settings** (`/settings`): per-user prefs (e.g. metric hover explainers),
  persisted via `users.settings` + `PATCH /auth/settings`.

### Strategy chat provider
`STRATEGY_CHAT_PROVIDER=api` (Anthropic key) or `claude_code` (local Claude Code
subscription via `scripts/claude_bridge.py` — auto-started by the launchd agent
`com.loaded.claude-bridge`; install with `scripts/install_claude_bridge_agent.sh`).
In `claude_code` mode the chat fetches market data through the app's own tool
protocol (get_quote / get_daily_history / get_most_active / get_fundamentals) —
never the host's MCP connectors.
