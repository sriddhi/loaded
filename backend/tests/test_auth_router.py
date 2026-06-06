"""
Integration tests for auth router endpoints.
Uses FastAPI TestClient with mocked DB helpers.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-that-is-long-enough-for-testing-purposes-only",
)

import app.auth.router  # ensure module is loaded for patch to resolve  # noqa: F401
from app.auth.security import create_access_token, create_refresh_token, hash_password  # noqa: E402

_NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def admin_row():
    return {
        "id": 1,
        "email": "admin@loaded.app",
        "password_hash": hash_password("adminpass1"),
        "role": "admin",
        "is_active": True,
        "created_at": _NOW,
    }


@pytest.fixture(scope="module")
def client_row():
    return {
        "id": 2,
        "email": "client@loaded.app",
        "password_hash": hash_password("clientpass1"),
        "role": "client",
        "is_active": True,
        "created_at": _NOW,
    }


@pytest.fixture(scope="module")
def inactive_row():
    return {
        "id": 3,
        "email": "inactive@loaded.app",
        "password_hash": hash_password("inactivepass1"),
        "role": "client",
        "is_active": False,
        "created_at": _NOW,
    }


@pytest.fixture(scope="module")
def admin_token():
    return create_access_token(1, "admin")


@pytest.fixture(scope="module")
def client_token():
    return create_access_token(2, "client")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _tc() -> TestClient:
    from app.main import app

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn)
    mock_pool.close = AsyncMock()
    app.state.pool = mock_pool
    return TestClient(app, raise_server_exceptions=False)


# ── Register ───────────────────────────────────────────────────────────────────


def test_register_success(client_row):
    new_user = {**client_row, "id": 99, "email": "new@loaded.app"}
    with (
        patch("app.auth.router.get_user_by_email", AsyncMock(return_value=None)),
        patch("app.auth.router.create_user", AsyncMock(return_value=new_user)),
    ):
        resp = _tc().post(
            "/auth/register", json={"email": "new@loaded.app", "password": "securepass"}
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@loaded.app"
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_email(client_row):
    with patch("app.auth.router.get_user_by_email", AsyncMock(return_value=client_row)):
        resp = _tc().post(
            "/auth/register", json={"email": "client@loaded.app", "password": "securepass"}
        )
    assert resp.status_code == 409


def test_register_defaults_to_client_role(client_row):
    new_user = {**client_row, "id": 10, "email": "x@loaded.app"}
    with (
        patch("app.auth.router.get_user_by_email", AsyncMock(return_value=None)),
        patch("app.auth.router.create_user", AsyncMock(return_value=new_user)) as mock_create,
    ):
        _tc().post("/auth/register", json={"email": "x@loaded.app", "password": "securepass"})
    mock_create.assert_called_once()
    assert mock_create.call_args[0][3] == "client"


def test_register_without_token_cannot_set_admin_role(client_row):
    new_user = {**client_row, "id": 11, "email": "sneaky@loaded.app"}
    with (
        patch("app.auth.router.get_user_by_email", AsyncMock(return_value=None)),
        patch("app.auth.router.create_user", AsyncMock(return_value=new_user)) as mock_create,
    ):
        _tc().post(
            "/auth/register",
            json={"email": "sneaky@loaded.app", "password": "securepass", "role": "admin"},
        )
    mock_create.assert_called_once()
    assert mock_create.call_args[0][3] == "client"


# ── Login ──────────────────────────────────────────────────────────────────────


def test_login_success(admin_row):
    with patch("app.auth.router.get_user_by_email", AsyncMock(return_value=admin_row)):
        resp = _tc().post(
            "/auth/login", data={"username": "admin@loaded.app", "password": "adminpass1"}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(admin_row):
    with patch("app.auth.router.get_user_by_email", AsyncMock(return_value=admin_row)):
        resp = _tc().post(
            "/auth/login", data={"username": "admin@loaded.app", "password": "wrongpassword"}
        )
    assert resp.status_code == 401


def test_login_unknown_email():
    with patch("app.auth.router.get_user_by_email", AsyncMock(return_value=None)):
        resp = _tc().post(
            "/auth/login", data={"username": "nobody@loaded.app", "password": "anything"}
        )
    assert resp.status_code == 401


def test_login_inactive_user(inactive_row):
    with patch("app.auth.router.get_user_by_email", AsyncMock(return_value=inactive_row)):
        resp = _tc().post(
            "/auth/login", data={"username": "inactive@loaded.app", "password": "inactivepass1"}
        )
    assert resp.status_code == 401


# ── Refresh ────────────────────────────────────────────────────────────────────


def test_refresh_with_valid_refresh_token(admin_row):
    token = create_refresh_token(1)
    with patch("app.auth.router.get_user_by_id", AsyncMock(return_value=admin_row)):
        resp = _tc().post("/auth/refresh", json={"refresh_token": token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_refresh_with_access_token_rejected(admin_token):
    resp = _tc().post("/auth/refresh", json={"refresh_token": admin_token})
    assert resp.status_code == 401


# ── Me ─────────────────────────────────────────────────────────────────────────


def test_me_with_valid_token(real_auth, admin_token, admin_row):  # noqa: ARG001
    with patch("app.auth.db.get_user_by_id", AsyncMock(return_value=admin_row)):
        resp = _tc().get("/auth/me", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@loaded.app"


def test_me_with_no_token(real_auth):  # noqa: ARG001
    resp = _tc().get("/auth/me")
    assert resp.status_code == 401


def test_me_with_invalid_token(real_auth):  # noqa: ARG001
    resp = _tc().get("/auth/me", headers={"Authorization": "Bearer this.is.invalid"})
    assert resp.status_code == 401


# ── Admin: list users ──────────────────────────────────────────────────────────


def test_admin_get_users_success(admin_token, admin_row, client_row):
    with (
        patch("app.auth.db.get_user_by_id", AsyncMock(return_value=admin_row)),
        patch("app.auth.router.list_users", AsyncMock(return_value=[admin_row, client_row])),
    ):
        resp = _tc().get("/auth/users", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_non_admin_get_users_forbidden(real_auth, client_token, client_row):  # noqa: ARG001
    with patch("app.auth.db.get_user_by_id", AsyncMock(return_value=client_row)):
        resp = _tc().get("/auth/users", headers=_auth(client_token))
    assert resp.status_code == 403


# ── Admin: patch user ──────────────────────────────────────────────────────────


def test_admin_patch_user_role(admin_token, admin_row, client_row):
    updated = {**client_row, "role": "ops"}
    with (
        patch("app.auth.db.get_user_by_id", AsyncMock(return_value=admin_row)),
        patch("app.auth.router.update_user", AsyncMock(return_value=updated)),
    ):
        resp = _tc().patch("/auth/users/2", json={"role": "ops"}, headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["role"] == "ops"
