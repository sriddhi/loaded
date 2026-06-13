"""
Tests for Google OAuth login/signup, httpOnly cookies, and cookie-or-header auth.
DB + Google network are mocked; no real Google calls.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-that-is-long-enough-for-testing-purposes-only",
)
# Direct assignment (not setdefault): docker-compose passes these as empty
# strings, so setdefault would leave them blank and the endpoints would 503.
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:4000/api/auth/google/callback"
os.environ["FRONTEND_URL"] = "http://localhost:4000"

import app.auth.router  # noqa: E402, F401
from app.auth.security import create_access_token, create_refresh_token  # noqa: E402

_NOW = datetime.now(UTC)


def _google_user(**overrides):
    base = {
        "id": 7,
        "email": "g@example.com",
        "password_hash": None,
        "role": "client",
        "is_active": True,
        "created_at": _NOW,
        "auth_provider": "google",
        "google_sub": "google-sub-123",
    }
    base.update(overrides)
    return base


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


def _mock_token_exchange(id_token: str = "fake-id-token"):
    """Patch httpx.AsyncClient so the token exchange returns an id_token."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"id_token": id_token})

    client = MagicMock()
    client.post = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield client

    return patch("app.auth.router.httpx.AsyncClient", _ctx)


def _mock_verify(claims: dict):
    return patch(
        "app.auth.router.google_id_token.verify_oauth2_token",
        MagicMock(return_value=claims),
    )


# ── /auth/google/login ────────────────────────────────────────────────────────


def test_google_login_redirects_and_sets_state_cookie():
    resp = _tc().get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["location"]
    assert "state=" in resp.headers["location"]
    assert "oauth_state" in resp.cookies


def test_google_login_redirects_when_unconfigured():
    # Degrades gracefully (no raw 503 JSON) — redirect back to login with an error.
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
        resp = _tc().get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=oauth_unconfigured" in resp.headers["location"]


def test_auth_config_reports_google_disabled():
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
        resp = _tc().get("/auth/config")
    assert resp.status_code == 200
    assert resp.json()["google_enabled"] is False


# ── /auth/google/callback ─────────────────────────────────────────────────────


def test_callback_invalid_state_redirects_error():
    client = _tc()
    client.cookies.set("oauth_state", "expected")
    resp = client.get("/auth/google/callback?code=abc&state=WRONG", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=invalid_state" in resp.headers["location"]


def test_callback_email_unverified():
    client = _tc()
    client.cookies.set("oauth_state", "s1")
    with (
        _mock_token_exchange(),
        _mock_verify({"sub": "x", "email": "g@example.com", "email_verified": False}),
    ):
        resp = client.get("/auth/google/callback?code=abc&state=s1", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=email_unverified" in resp.headers["location"]


def test_callback_new_user_created_and_cookies_set():
    client = _tc()
    client.cookies.set("oauth_state", "s1")
    created = _google_user()
    with (
        _mock_token_exchange(),
        _mock_verify({"sub": "google-sub-123", "email": "g@example.com", "email_verified": True}),
        patch("app.auth.router.get_user_by_google_sub", AsyncMock(return_value=None)),
        patch("app.auth.router.get_user_by_email", AsyncMock(return_value=None)),
        patch("app.auth.router.create_oauth_user", AsyncMock(return_value=created)) as mock_create,
    ):
        resp = client.get("/auth/google/callback?code=abc&state=s1", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:4000"
    assert "access_token" in resp.cookies
    # OAuth users are always created as 'client'
    assert mock_create.call_args.kwargs.get("role", "client") == "client"


def test_callback_links_existing_local_account():
    client = _tc()
    client.cookies.set("oauth_state", "s1")
    local = _google_user(id=3, password_hash="hashed", auth_provider="local", google_sub=None)
    with (
        _mock_token_exchange(),
        _mock_verify({"sub": "google-sub-123", "email": "g@example.com", "email_verified": True}),
        patch("app.auth.router.get_user_by_google_sub", AsyncMock(return_value=None)),
        patch("app.auth.router.get_user_by_email", AsyncMock(return_value=local)),
        patch(
            "app.auth.router.link_google_to_user",
            AsyncMock(return_value=_google_user(id=3)),
        ) as mock_link,
    ):
        resp = client.get("/auth/google/callback?code=abc&state=s1", follow_redirects=False)
    assert resp.status_code == 302
    mock_link.assert_awaited_once()
    assert "access_token" in resp.cookies


def test_callback_existing_google_user_no_duplicate():
    client = _tc()
    client.cookies.set("oauth_state", "s1")
    with (
        _mock_token_exchange(),
        _mock_verify({"sub": "google-sub-123", "email": "g@example.com", "email_verified": True}),
        patch(
            "app.auth.router.get_user_by_google_sub",
            AsyncMock(return_value=_google_user()),
        ),
        patch("app.auth.router.create_oauth_user", AsyncMock()) as mock_create,
    ):
        resp = client.get("/auth/google/callback?code=abc&state=s1", follow_redirects=False)
    assert resp.status_code == 302
    mock_create.assert_not_called()


def test_callback_inactive_user_blocked():
    client = _tc()
    client.cookies.set("oauth_state", "s1")
    with (
        _mock_token_exchange(),
        _mock_verify({"sub": "google-sub-123", "email": "g@example.com", "email_verified": True}),
        patch(
            "app.auth.router.get_user_by_google_sub",
            AsyncMock(return_value=_google_user(is_active=False)),
        ),
    ):
        resp = client.get("/auth/google/callback?code=abc&state=s1", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=inactive" in resp.headers["location"]
    assert "access_token" not in resp.cookies


# ── Cookies on login / logout / cookie-based auth ─────────────────────────────


def test_login_sets_httponly_cookies():
    from app.auth.security import hash_password

    user = {
        "id": 2,
        "email": "c@example.com",
        "password_hash": hash_password("password1"),
        "role": "client",
        "is_active": True,
        "created_at": _NOW,
        "auth_provider": "local",
        "google_sub": None,
    }
    with patch("app.auth.router.get_user_by_email", AsyncMock(return_value=user)):
        resp = _tc().post(
            "/auth/login",
            data={"username": "c@example.com", "password": "password1"},
        )
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "httponly" in set_cookie.lower()


def test_logout_clears_cookies():
    resp = _tc().post("/auth/logout")
    assert resp.status_code == 204
    assert 'access_token=""' in resp.headers.get(
        "set-cookie", ""
    ) or "access_token=;" in resp.headers.get("set-cookie", "")


def test_get_current_user_resolves_cookie(real_auth):  # noqa: ARG001

    user = _google_user()
    token = create_access_token(user["id"], user["role"])
    # get_user_by_id is imported inside get_current_user from app.auth.db.
    with patch("app.auth.db.get_user_by_id", AsyncMock(return_value=user)):
        client = _tc()
        client.cookies.set("access_token", token)
        resp = client.get("/auth/me")  # no Authorization header
    assert resp.status_code == 200
    assert resp.json()["email"] == user["email"]


def test_refresh_reads_cookie(real_auth):  # noqa: ARG001
    user = _google_user()
    token = create_refresh_token(user["id"])
    with patch("app.auth.router.get_user_by_id", AsyncMock(return_value=user)):
        client = _tc()
        client.cookies.set("refresh_token", token)
        resp = client.post("/auth/refresh")  # no body
    assert resp.status_code == 200
    assert "access_token" in resp.json()
