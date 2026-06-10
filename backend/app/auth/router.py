"""
Auth router — /auth prefix.

Public endpoints: /auth/login, /auth/register, /auth/refresh
Protected endpoints: /auth/me (any authenticated user), /auth/users (admin only)
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any
from urllib.parse import urlencode

import asyncpg
import httpx
from app.auth.db import (
    create_oauth_user,
    create_user,
    get_user_by_email,
    get_user_by_google_sub,
    get_user_by_id,
    link_google_to_user,
    list_users,
    update_user,
)
from app.auth.models import RefreshRequest, TokenResponse, UserCreate, UserOut, UserUpdate
from app.auth.security import (
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    require_role,
    set_auth_cookies,
    verify_password,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_STATE_COOKIE = "oauth_state"


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def _google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "")


def _google_client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "")


def _google_redirect_uri() -> str:
    return os.getenv("GOOGLE_REDIRECT_URI", "")


def _login_error_redirect(reason: str) -> RedirectResponse:
    """Redirect the browser back to the frontend login page with an error code."""
    return RedirectResponse(url=f"{_frontend_url()}/login?error={reason}", status_code=302)


def _get_db_pool(request: Request) -> Any:
    return request.app.state.pool


async def _conn(request: Request) -> Any:
    pool = _get_db_pool(request)
    async with pool.acquire() as conn:
        yield conn


# ── Register ───────────────────────────────────────────────────────────────────


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    request: Request,
    conn: asyncpg.Connection = Depends(_conn),
) -> Any:
    # Only an authenticated admin may create admin/ops accounts
    requested_role = body.role
    if requested_role in ("admin", "ops"):
        token = request.headers.get("Authorization", "")
        if token.startswith("Bearer "):
            try:
                payload = decode_token(token[7:])
                if payload.get("role") != "admin":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only admins can assign admin or ops roles",
                    )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only admins can assign admin or ops roles",
                ) from exc
        else:
            # No token — force to client
            requested_role = "client"

    existing = await get_user_by_email(conn, body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    hashed = hash_password(body.password)
    user = await create_user(conn, body.email, hashed, requested_role)
    return user


# ── Login ──────────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    conn: asyncpg.Connection = Depends(_conn),
) -> Any:
    user = await get_user_by_email(conn, form.username)
    # password_hash may be NULL for OAuth-only accounts — reject password login then.
    if (
        not user
        or not user["password_hash"]
        or not verify_password(form.password, user["password_hash"])
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is inactive")

    access = create_access_token(user["id"], user["role"])
    refresh = create_refresh_token(user["id"])
    set_auth_cookies(response, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


# ── Refresh ────────────────────────────────────────────────────────────────────


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    conn: asyncpg.Connection = Depends(_conn),
) -> Any:
    # Refresh token from the request body, else the refresh_token cookie.
    token = (body.refresh_token if body else None) or request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )

    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = int(payload["sub"])
    user = await get_user_by_id(conn, user_id)
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )

    access = create_access_token(user["id"], user["role"])
    new_refresh = create_refresh_token(user["id"])
    set_auth_cookies(response, access, new_refresh)
    return TokenResponse(access_token=access, refresh_token=new_refresh)


# ── Logout ─────────────────────────────────────────────────────────────────────


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> Response:
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# ── Google OAuth ─────────────────────────────────────────────────────────────


@router.get("/google/login")
@limiter.limit("10/minute")
async def google_login(request: Request) -> RedirectResponse:
    """Begin the Google authorization-code flow. Sets a CSRF state cookie."""
    if not _google_client_id() or not _google_redirect_uri():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": _google_client_id(),
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    redirect = RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    redirect.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes"),
        samesite=os.getenv("COOKIE_SAMESITE", "lax").lower(),  # type: ignore[arg-type]
        path="/auth/google",
    )
    return redirect


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    conn: asyncpg.Connection = Depends(_conn),
) -> RedirectResponse:
    """Handle Google's redirect: verify, upsert/link the user, set auth cookies."""
    if error or not code:
        return _login_error_redirect("oauth_denied")

    # CSRF: state must match the state cookie set at /google/login.
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        resp = _login_error_redirect("invalid_state")
        resp.delete_cookie(OAUTH_STATE_COOKIE, path="/auth/google")
        return resp

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": _google_client_id(),
                    "client_secret": _google_client_secret(),
                    "redirect_uri": _google_redirect_uri(),
                    "grant_type": "authorization_code",
                },
            )
        if token_resp.status_code != 200:
            logger.warning("Google token exchange failed: HTTP %s", token_resp.status_code)
            return _login_error_redirect("oauth_failed")

        raw_id_token = token_resp.json().get("id_token")
        if not raw_id_token:
            return _login_error_redirect("oauth_failed")

        claims = google_id_token.verify_oauth2_token(
            raw_id_token, google_requests.Request(), _google_client_id()
        )
    except Exception:
        logger.warning("Google OAuth verification failed", exc_info=False)
        return _login_error_redirect("oauth_failed")

    if not claims.get("email_verified"):
        return _login_error_redirect("email_unverified")

    google_sub = claims.get("sub")
    email = claims.get("email")
    if not google_sub or not email:
        return _login_error_redirect("oauth_failed")

    user = await _resolve_google_user(conn, google_sub=google_sub, email=email)
    if user is None:
        return _login_error_redirect("oauth_failed")
    if not user["is_active"]:
        return _login_error_redirect("inactive")

    access = create_access_token(user["id"], user["role"])
    refresh = create_refresh_token(user["id"])
    redirect = RedirectResponse(url=_frontend_url(), status_code=302)
    set_auth_cookies(redirect, access, refresh)
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/auth/google")
    return redirect


async def _resolve_google_user(conn: asyncpg.Connection, *, google_sub: str, email: str) -> Any:
    """Find or create the user for a verified Google identity.

    Order: match by google_sub → else by email (link existing local account) →
    else create a new client account. OAuth never assigns admin/ops.
    """
    user = await get_user_by_google_sub(conn, google_sub)
    if user:
        return user

    existing = await get_user_by_email(conn, email)
    if existing:
        # Auto-link the verified Google identity to the existing account.
        return await link_google_to_user(conn, existing["id"], google_sub)

    return await create_oauth_user(conn, email, google_sub, role="client")


# ── Me ─────────────────────────────────────────────────────────────────────────


@router.get("/me", response_model=UserOut)
async def me(current_user: dict[str, Any] = Depends(get_current_user)) -> Any:
    return current_user


# ── Admin: list users ──────────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserOut])
async def get_users(
    _admin: dict[str, Any] = Depends(require_role("admin")),
    conn: asyncpg.Connection = Depends(_conn),
) -> Any:
    return await list_users(conn)


# ── Admin: update user ─────────────────────────────────────────────────────────


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: int,
    body: UserUpdate,
    _admin: dict[str, Any] = Depends(require_role("admin")),
    conn: asyncpg.Connection = Depends(_conn),
) -> Any:
    user = await update_user(conn, user_id, role=body.role, is_active=body.is_active)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
