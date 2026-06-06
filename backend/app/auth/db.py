"""
Raw asyncpg DB helpers for the users table.
"""

from __future__ import annotations

from typing import Any

import asyncpg


async def create_user(
    conn: asyncpg.Connection,
    email: str,
    password_hash: str,
    role: str = "client",
) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, password_hash, role)
        VALUES ($1, $2, $3::user_role)
        RETURNING id, email, role, is_active, created_at
        """,
        email,
        password_hash,
        role,
    )
    return dict(row)


async def get_user_by_email(conn: asyncpg.Connection, email: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT id, email, password_hash, role, is_active, created_at FROM users WHERE email = $1",
        email,
    )
    return dict(row) if row else None


async def get_user_by_id(conn: asyncpg.Connection, user_id: int) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT id, email, password_hash, role, is_active, created_at FROM users WHERE id = $1",
        user_id,
    )
    return dict(row) if row else None


async def list_users(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    rows = await conn.fetch("SELECT id, email, role, is_active, created_at FROM users ORDER BY id")
    return [dict(r) for r in rows]


async def update_user(
    conn: asyncpg.Connection,
    user_id: int,
    role: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any] | None:
    sets = []
    values: list[Any] = []
    idx = 1
    if role is not None:
        sets.append(f"role = ${idx}::user_role")
        values.append(role)
        idx += 1
    if is_active is not None:
        sets.append(f"is_active = ${idx}")
        values.append(is_active)
        idx += 1
    if not sets:
        return await get_user_by_id(conn, user_id)
    values.append(user_id)
    row = await conn.fetchrow(
        f"UPDATE users SET {', '.join(sets)} WHERE id = ${idx} RETURNING id, email, role, is_active, created_at",
        *values,
    )
    return dict(row) if row else None
