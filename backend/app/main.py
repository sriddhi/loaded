import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import asyncpg
from app.alpaca_client import alpaca_ok
from app.strategies.router import router as strategies_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DB_MIGRATIONS = """
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_url = os.getenv("DATABASE_URL")
    app.state.db_url = db_url
    try:
        conn = await asyncpg.connect(db_url)
        await conn.execute(DB_MIGRATIONS)
        await conn.close()
    except Exception as e:
        print(f"[startup] DB migration warning: {e}")
    yield


app = FastAPI(title="Loaded API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(strategies_router)


async def db_ok() -> bool:
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True
    except Exception:
        return False


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
