"""Tests for trading job persistence, multi-user registry, and user isolation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.auth.security import get_current_user
from app.main import app
from fastapi.testclient import TestClient

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(user_id: int = 1, role: str = "user") -> dict:
    return {"id": user_id, "role": role, "email": "test@example.com", "is_active": True}


def _make_admin() -> dict:
    return _make_user(user_id=1, role="admin")


def _auth(user: MagicMock) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def _clear() -> None:
    app.dependency_overrides.clear()


def _mock_pool(rows: list | None = None, scalar: object = None) -> MagicMock:
    """Build a mock asyncpg pool whose acquire() yields a mock connection."""
    conn = AsyncMock()
    if rows is not None:
        conn.fetch = AsyncMock(return_value=rows)
        conn.fetchrow = AsyncMock(return_value=rows[0] if rows else None)
    if scalar is not None:
        conn.fetchval = AsyncMock(return_value=scalar)
    conn.execute = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


# ── Job registry API ─────────────────────────────────────────────────────────


def test_list_jobs_unauthorized():
    _clear()
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/trading/jobs")
    assert resp.status_code == 401
    _clear()


def test_create_job_unauthorized():
    _clear()
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/trading/jobs", json={"name": "my_job", "strategy": "orb"})
    assert resp.status_code == 401
    _clear()


def test_list_jobs_returns_schema():
    """GET /trading/jobs returns a list (may be empty if DB not available)."""
    _auth(_make_user())

    pool, conn = _mock_pool(rows=[])
    app.state.pool = pool  # type: ignore[attr-defined]
    # Patch request.state.user via dependency override already done above
    # We also need to ensure conn.fetch returns []
    conn.fetch = AsyncMock(return_value=[])

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/trading/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    _clear()


def test_create_job_duplicate_name():
    """POST /trading/jobs with a duplicate name returns 409."""
    _auth(_make_user(user_id=2))

    pool, conn = _mock_pool()
    # Simulate existing job found
    existing_row = MagicMock()
    existing_row.__getitem__ = MagicMock(return_value=42)
    conn.fetchrow = AsyncMock(return_value=existing_row)
    app.state.pool = pool  # type: ignore[attr-defined]

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/trading/jobs", json={"name": "my_job", "strategy": "orb"})
    assert resp.status_code == 409
    _clear()


def test_start_job_permission_denied():
    """User cannot start a job they don't own (job_belongs_to_user returns False)."""
    _auth(_make_user(user_id=99))

    pool, conn = _mock_pool()
    conn.fetchrow = AsyncMock(
        side_effect=[
            # can_mutate_job: job is owned by user_id=1, not 99, and is 'user' type
            {"owner_id": 1, "job_type": "user"},
        ]
    )
    app.state.pool = pool  # type: ignore[attr-defined]

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/trading/jobs/5/start")
    assert resp.status_code == 403
    _clear()


def test_start_job_isolation_conflict():
    """User with a running job gets 409 when starting another."""
    _auth(_make_user(user_id=3))

    pool, conn = _mock_pool()
    # can_mutate_job → owns it
    # user_has_running_job → True (count=1)
    conn.fetchrow = AsyncMock(return_value={"owner_id": 3, "job_type": "user"})
    conn.fetchval = AsyncMock(return_value=1)  # count of running jobs = 1
    app.state.pool = pool  # type: ignore[attr-defined]

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/trading/jobs/7/start")
    assert resp.status_code == 409
    assert "already have a running job" in resp.json()["detail"]
    _clear()


def test_get_today_session_no_session():
    """Returns {session: null, events: []} when no session exists today."""
    _auth(_make_user(user_id=1))

    pool, conn = _mock_pool()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"owner_id": 1, "job_type": "user"},  # job_belongs_to_user
            None,  # get_session_today → no session
        ]
    )
    app.state.pool = pool  # type: ignore[attr-defined]

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/trading/jobs/1/sessions/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session"] is None
    assert body["events"] == []
    _clear()


def test_get_session_events_forbidden():
    """User B cannot access user A's session events."""
    _auth(_make_user(user_id=99))

    pool, conn = _mock_pool()
    conn.fetchrow = AsyncMock(
        return_value={"owner_id": 1, "job_type": "user"}  # owned by user 1, not 99
    )
    app.state.pool = pool  # type: ignore[attr-defined]

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/trading/jobs/1/sessions/10/events")
    assert resp.status_code == 403
    _clear()


def test_admin_can_see_all_jobs():
    """Admin gets all jobs including system and other users'."""
    _auth(_make_admin())

    job_row = {
        "id": 1,
        "name": "spy_orb_0dte",
        "strategy": "orb",
        "job_type": "system",
        "owner_id": None,
        "config": {},
        "status": "idle",
        "is_active": True,
        "created_at": None,
    }
    pool, conn = _mock_pool(rows=[job_row])
    conn.fetch = AsyncMock(return_value=[job_row])
    app.state.pool = pool  # type: ignore[attr-defined]

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/trading/jobs")
    assert resp.status_code == 200
    _clear()


def test_stop_specific_job_access_denied():
    """User cannot stop another user's job."""
    _auth(_make_user(user_id=50))

    pool, conn = _mock_pool()
    conn.fetchrow = AsyncMock(
        return_value={"owner_id": 1, "job_type": "user"}  # owned by user 1
    )
    app.state.pool = pool  # type: ignore[attr-defined]

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/trading/jobs/1/stop")
    assert resp.status_code == 403
    _clear()
