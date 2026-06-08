"""
DB helpers for the trading module.

All SQL lives here — no raw queries in router.py or job.py.
Each function accepts an asyncpg Connection (acquired/released by the caller).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import asyncpg

# ── Job registry ──────────────────────────────────────────────────────────────


async def get_or_create_job(
    conn: asyncpg.Connection,
    *,
    name: str,
    strategy: str,
    job_type: str = "user",
    owner_id: int | None,
    config: dict,
) -> int:
    """Return job_id. Creates the row if it doesn't exist yet.

    NULL owner_id is handled with IS NULL check (SQL UNIQUE constraint
    does not deduplicate NULLs, so we use SELECT-then-INSERT).
    """
    if owner_id is None:
        # System job: find by name + null owner
        existing = await conn.fetchrow(
            "SELECT id FROM trading_jobs WHERE name = $1 AND owner_id IS NULL",
            name,
        )
        if existing:
            await conn.execute(
                "UPDATE trading_jobs SET updated_at = NOW() WHERE id = $1",
                existing["id"],
            )
            return int(existing["id"])
        row = await conn.fetchrow(
            """
            INSERT INTO trading_jobs (name, strategy, job_type, owner_id, config)
            VALUES ($1, $2, $3, NULL, $4)
            RETURNING id
            """,
            name,
            strategy,
            job_type,
            json.dumps(config),
        )
    else:
        row = await conn.fetchrow(
            """
            INSERT INTO trading_jobs (name, strategy, job_type, owner_id, config)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (owner_id, name) DO UPDATE
                SET updated_at = NOW()
            RETURNING id
            """,
            name,
            strategy,
            job_type,
            owner_id,
            json.dumps(config),
        )
    assert row is not None
    return int(row["id"])


async def get_job(conn: asyncpg.Connection, job_id: int) -> dict | None:
    row = await conn.fetchrow("SELECT * FROM trading_jobs WHERE id = $1", job_id)
    return dict(row) if row else None


async def set_job_status(conn: asyncpg.Connection, job_id: int, status: str) -> None:
    await conn.execute(
        "UPDATE trading_jobs SET status = $1, updated_at = NOW() WHERE id = $2",
        status,
        job_id,
    )


async def get_jobs(
    conn: asyncpg.Connection,
    owner_id: int | None,
    *,
    is_admin: bool = False,
) -> list[dict]:
    """Return jobs visible to this user: own jobs + system jobs.
    Admins see all jobs.
    """
    if is_admin:
        rows = await conn.fetch(
            "SELECT * FROM trading_jobs WHERE is_active = TRUE ORDER BY created_at DESC"
        )
    else:
        rows = await conn.fetch(
            """
            SELECT * FROM trading_jobs
            WHERE is_active = TRUE
              AND (owner_id = $1 OR job_type = 'system')
            ORDER BY job_type DESC, created_at DESC
            """,
            owner_id,
        )
    return [dict(r) for r in rows]


async def user_has_running_job(conn: asyncpg.Connection, owner_id: int) -> bool:
    """True if this user already has a job with status='running'."""
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM trading_jobs WHERE owner_id = $1 AND status = 'running'",
        owner_id,
    )
    return int(count) > 0


async def job_belongs_to_user(
    conn: asyncpg.Connection, job_id: int, owner_id: int, *, is_admin: bool = False
) -> bool:
    """True if the user owns this job, or it's a system job, or user is admin."""
    if is_admin:
        return True
    row = await conn.fetchrow("SELECT owner_id, job_type FROM trading_jobs WHERE id = $1", job_id)
    if not row:
        return False
    return bool(row["owner_id"] == owner_id or row["job_type"] == "system")


async def can_mutate_job(
    conn: asyncpg.Connection, job_id: int, owner_id: int, *, is_admin: bool = False
) -> bool:
    """True if the user can start/stop this job (must own it; system jobs need admin)."""
    if is_admin:
        return True
    row = await conn.fetchrow("SELECT owner_id, job_type FROM trading_jobs WHERE id = $1", job_id)
    if not row:
        return False
    if row["job_type"] == "system":
        return False  # non-admins cannot start/stop system jobs
    return bool(row["owner_id"] == owner_id)


# ── Sessions ──────────────────────────────────────────────────────────────────


async def get_or_create_session(conn: asyncpg.Connection, job_id: int, session_date: date) -> int:
    """Return session_id. Creates one row per job per day."""
    row = await conn.fetchrow(
        """
        INSERT INTO trading_sessions (job_id, session_date)
        VALUES ($1, $2)
        ON CONFLICT (job_id, session_date) DO UPDATE
            SET status = CASE
                WHEN trading_sessions.status = 'closed' THEN 'open'
                ELSE trading_sessions.status
            END
        RETURNING id
        """,
        job_id,
        session_date,
    )
    return int(row["id"])


async def update_session_orb(
    conn: asyncpg.Connection,
    session_id: int,
    *,
    orb_high: float,
    orb_low: float,
    orb_width: float,
    orb_established_at: datetime,
) -> None:
    await conn.execute(
        """
        UPDATE trading_sessions
        SET orb_high = $1, orb_low = $2, orb_width = $3, orb_established_at = $4
        WHERE id = $5
        """,
        orb_high,
        orb_low,
        orb_width,
        orb_established_at,
        session_id,
    )


async def close_session(conn: asyncpg.Connection, session_id: int, *, pnl_cents: int) -> None:
    await conn.execute(
        """
        UPDATE trading_sessions
        SET status = 'closed', closed_at = NOW(), daily_pnl_cents = $1
        WHERE id = $2
        """,
        pnl_cents,
        session_id,
    )


async def increment_session_counter(
    conn: asyncpg.Connection, session_id: int, *, field: str
) -> None:
    """Increment total_entries or total_exits by 1."""
    allowed = {"total_entries", "total_exits"}
    if field not in allowed:
        raise ValueError(f"field must be one of {allowed}")
    await conn.execute(
        f"UPDATE trading_sessions SET {field} = {field} + 1 WHERE id = $1",  # noqa: S608
        session_id,
    )


async def get_session_today(conn: asyncpg.Connection, job_id: int) -> dict | None:
    today = datetime.now(tz=UTC).date()
    row = await conn.fetchrow(
        "SELECT * FROM trading_sessions WHERE job_id = $1 AND session_date = $2",
        job_id,
        today,
    )
    return dict(row) if row else None


async def get_sessions(conn: asyncpg.Connection, job_id: int, limit: int = 30) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM trading_sessions WHERE job_id = $1 ORDER BY session_date DESC LIMIT $2",
        job_id,
        limit,
    )
    return [dict(r) for r in rows]


# ── Events ────────────────────────────────────────────────────────────────────


async def log_event(
    conn: asyncpg.Connection,
    job_id: int,
    session_id: int | None,
    event_type: str,
    *,
    direction: str | None = None,
    contract_symbol: str | None = None,
    contracts: int | None = None,
    spy_price: float | None = None,
    orb_high: float | None = None,
    orb_low: float | None = None,
    signal_streak: int | None = None,
    entry_counts: dict | None = None,
    option_price: float | None = None,
    pnl_cents: int | None = None,
    order_id: str | None = None,
    reason: str | None = None,
    decision: str | None = None,
    meta: dict | None = None,
) -> None:
    """Insert one row into trading_events."""
    await conn.execute(
        """
        INSERT INTO trading_events (
            job_id, session_id, event_type,
            direction, contract_symbol, contracts,
            spy_price, orb_high, orb_low,
            signal_streak, entry_counts, option_price,
            pnl_cents, order_id, reason, decision, meta
        ) VALUES (
            $1, $2, $3,
            $4, $5, $6,
            $7, $8, $9,
            $10, $11, $12,
            $13, $14, $15, $16, $17
        )
        """,
        job_id,
        session_id,
        event_type,
        direction,
        contract_symbol,
        contracts,
        spy_price,
        orb_high,
        orb_low,
        signal_streak,
        json.dumps(entry_counts) if entry_counts is not None else None,
        option_price,
        pnl_cents,
        order_id,
        reason,
        decision,
        json.dumps(meta) if meta is not None else None,
    )


async def get_events(conn: asyncpg.Connection, session_id: int, limit: int = 500) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT * FROM trading_events
        WHERE session_id = $1
        ORDER BY time DESC
        LIMIT $2
        """,
        session_id,
        limit,
    )
    return [dict(r) for r in rows]


async def get_events_by_job(conn: asyncpg.Connection, job_id: int, limit: int = 200) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT * FROM trading_events
        WHERE job_id = $1
        ORDER BY time DESC
        LIMIT $2
        """,
        job_id,
        limit,
    )
    return [dict(r) for r in rows]
