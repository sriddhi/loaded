"""
Unit tests for auth/db.py — asyncpg helper stubs using MagicMock connections.
No live DB required.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.auth.db import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_user,
)

_NOW = datetime.now(UTC)

_USER_ROW = {
    "id": 1,
    "email": "test@example.com",
    "password_hash": "hashed",
    "role": "client",
    "is_active": True,
    "created_at": _NOW,
}


def _mock_conn(fetchrow_return=None, fetch_return=None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value=MagicMock(**fetchrow_return) if fetchrow_return else None
    )
    if fetchrow_return:
        conn.fetchrow.return_value.__iter__ = lambda s: iter(fetchrow_return.items())
        conn.fetchrow.return_value.keys = lambda: fetchrow_return.keys()
        # Make dict(row) work
        conn.fetchrow.return_value.__class__ = dict
        conn.fetchrow.return_value = dict(fetchrow_return)  # type: ignore
    conn.fetch = AsyncMock(return_value=[dict(_USER_ROW)] if fetch_return is None else fetch_return)
    return conn


@pytest.mark.asyncio
async def test_create_user_returns_dict():
    conn = _mock_conn(
        fetchrow_return={
            "id": 1,
            "email": "a@b.com",
            "role": "client",
            "is_active": True,
            "created_at": _NOW,
        }
    )
    result = await create_user(conn, "a@b.com", "hash", "client")
    assert result["email"] == "a@b.com"
    assert result["role"] == "client"
    conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_by_email_returns_none_for_unknown():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    result = await get_user_by_email(conn, "nobody@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_by_id_returns_dict():
    conn = _mock_conn(fetchrow_return=_USER_ROW)
    result = await get_user_by_id(conn, 1)
    assert result is not None
    assert result["id"] == 1


@pytest.mark.asyncio
async def test_update_user_changes_role():
    updated = {**_USER_ROW, "role": "ops"}
    conn = _mock_conn(fetchrow_return=updated)
    result = await update_user(conn, 1, role="ops")
    assert result is not None
    assert result["role"] == "ops"
