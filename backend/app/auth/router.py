"""
Auth router — /auth prefix.

Public endpoints: /auth/login, /auth/register, /auth/refresh
Protected endpoints: /auth/me (any authenticated user), /auth/users (admin only)
"""

from __future__ import annotations

from typing import Any

import asyncpg
from app.auth.db import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)
from app.auth.models import RefreshRequest, TokenResponse, UserCreate, UserOut, UserUpdate
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


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
    form: OAuth2PasswordRequestForm = Depends(),
    conn: asyncpg.Connection = Depends(_conn),
) -> Any:
    user = await get_user_by_email(conn, form.username)
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is inactive")

    return TokenResponse(
        access_token=create_access_token(user["id"], user["role"]),
        refresh_token=create_refresh_token(user["id"]),
    )


# ── Refresh ────────────────────────────────────────────────────────────────────


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    conn: asyncpg.Connection = Depends(_conn),
) -> Any:
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = int(payload["sub"])
    user = await get_user_by_id(conn, user_id)
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )

    return TokenResponse(
        access_token=create_access_token(user["id"], user["role"]),
        refresh_token=create_refresh_token(user["id"]),
    )


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
