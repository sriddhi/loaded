# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Loaded

Loaded is the enterprise-grade evolution of the Vertex trading strategy POC. It is a dockerized full-stack web application targeting both GenZ traders and seasoned professionals — minimal, clean, data-first design.

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
- `http://localhost:3000` — Next.js frontend
- `http://localhost:8000` — FastAPI backend
- PostgreSQL runs internally only (no exposed port)

## Architecture

```
loaded/
├── frontend/          Next.js 14 (TypeScript, standalone output)
│   └── src/
│       ├── app/       App Router pages + global styles
│       └── components/
├── backend/
│   └── app/
│       └── main.py   FastAPI entry point
├── docker-compose.yml All three services + loaded_net bridge network
└── .env.example       Copy to .env before running
```

**Data flow:** Frontend polls `NEXT_PUBLIC_API_URL/health` every 30 seconds. The backend checks PostgreSQL connectivity on each health request via `asyncpg` (no connection pool — opens and closes per request currently).

**Networking:** All containers share `loaded_net` bridge network. Service-to-service DNS uses container service names (`postgres`, `backend`, `frontend`). PostgreSQL has no exposed host port — only reachable from within the Docker network.

**Frontend build:** Uses `output: "standalone"` in `next.config.mjs` — the Docker image copies `.next/standalone` and runs `node server.js` directly (no `next start`).

## Environment

Copy `.env.example` to `.env` before first run:
```bash
cp .env.example .env
```

Key variables:
- `POSTGRES_PASSWORD` — shared by compose and backend `DATABASE_URL`
- `NEXT_PUBLIC_API_URL` — set to `http://localhost:8000` for local dev

## Backend

FastAPI with `asyncpg` (raw PostgreSQL, no ORM yet). New endpoints go in `backend/app/main.py` or new router files imported there. After changes, rebuild:

```bash
docker compose build backend && docker compose up -d backend
```

## Frontend

Next.js 14 App Router. Components in `src/components/`, pages in `src/app/`. After changes, rebuild:

```bash
docker compose build frontend && docker compose up -d frontend
```

`NEXT_PUBLIC_*` env vars are baked in at build time — changing them requires a rebuild.

## Design Principles

- Near-black background (`#0a0a0a`), off-white foreground (`#f5f5f5`)
- Accent: electric yellow (`#e8ff47`)
- Monospace for all data/status text (`SF Mono`, `Fira Code`, `Cascadia Code`)
- No unnecessary UI — every element earns its place
- Audience: GenZ traders who value speed + simplicity, and seasoned traders who value data density
