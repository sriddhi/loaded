from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import os
from datetime import datetime, timezone

app = FastAPI(title="Loaded API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def db_ok() -> bool:
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True
    except Exception:
        return False


@app.get("/health")
async def health():
    db = await db_ok()
    return {
        "status": "online",
        "db": "connected" if db else "disconnected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
