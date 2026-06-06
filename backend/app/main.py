import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import asyncpg
from app.alpaca.router import router as alpaca_router
from app.alpaca_client import alpaca_ok
from app.auth.middleware import DocsAuthMiddleware
from app.auth.router import router as auth_router
from app.auth.security import get_current_user
from app.marketdata.router import router as marketdata_router
from app.strategies.router import router as strategies_router
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

DB_MIGRATIONS = """
DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('admin', 'client', 'ops');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          user_role NOT NULL DEFAULT 'client',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    config_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluations (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id),
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    metrics_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


async def _seed_admin(pool: asyncpg.Pool) -> None:
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return
    from app.auth.db import create_user, get_user_by_email
    from app.auth.security import hash_password

    async with pool.acquire() as conn:
        existing = await get_user_by_email(conn, email)
        if existing:
            return
        await create_user(conn, email, hash_password(password), role="admin")
        print(f"[startup] Admin user seeded: {email}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Validate JWT secret is configured
    if not os.getenv("JWT_SECRET_KEY"):
        raise RuntimeError(
            "JWT_SECRET_KEY environment variable is not set. "
            "Set it to a random 64-character hex string before starting the server."
        )

    db_url = os.getenv("DATABASE_URL")
    app.state.db_url = db_url

    pool = await asyncpg.create_pool(db_url)
    app.state.pool = pool

    try:
        async with pool.acquire() as conn:
            await conn.execute(DB_MIGRATIONS)
    except Exception as e:
        print(f"[startup] DB migration warning: {e}")

    await _seed_admin(pool)

    yield

    await pool.close()


app = FastAPI(title="Loaded API", version="0.1.0", lifespan=lifespan)

# ── Middleware ─────────────────────────────────────────────────────────────────

app.add_middleware(DocsAuthMiddleware)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# ── Rate limiter ───────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ── Routers ────────────────────────────────────────────────────────────────────

# Auth routes are public — no global dependency
app.include_router(auth_router)

# All other routes require a valid JWT
_auth_dep = [Depends(get_current_user)]
app.include_router(strategies_router, dependencies=_auth_dep)
app.include_router(alpaca_router, dependencies=_auth_dep)
app.include_router(marketdata_router, dependencies=_auth_dep)


# ── DB helpers ─────────────────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """Yield a single connection from the pool (used by auth security module)."""
    async with app.state.pool.acquire() as conn:
        yield conn


async def db_ok() -> bool:
    try:
        async with app.state.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


# ── Health ─────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, Any]:
    db = await db_ok()
    alpaca_connected, alpaca_error = alpaca_ok()
    return {
        "status": "online",
        "db": "connected" if db else "disconnected",
        "alpaca": "connected" if alpaca_connected else "disconnected",
        "alpaca_error": alpaca_error,
        "timestamp": datetime.now(UTC).isoformat(),
    }
