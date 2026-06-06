"""
Password hashing, JWT creation/decoding, and FastAPI auth dependencies.
"""

from __future__ import annotations

import os
from datetime import UTC
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY environment variable is not set. "
            "Set it to a random 64-character hex string before starting the server."
        )
    return secret


def _algorithm() -> str:
    return os.getenv("JWT_ALGORITHM", "HS256")


def _access_expire_minutes() -> int:
    return int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))


def _refresh_expire_days() -> int:
    return int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ── Password ───────────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return str(pwd_context.hash(plain))


def verify_password(plain: str, hashed: str) -> bool:
    return bool(pwd_context.verify(plain, hashed))


# ── JWT ────────────────────────────────────────────────────────────────────────


def create_access_token(user_id: int, role: str) -> str:
    from datetime import datetime, timedelta

    expire = datetime.now(UTC) + timedelta(minutes=_access_expire_minutes())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return str(jwt.encode(payload, _secret(), algorithm=_algorithm()))


def create_refresh_token(user_id: int) -> str:
    from datetime import datetime, timedelta

    expire = datetime.now(UTC) + timedelta(days=_refresh_expire_days())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": expire,
    }
    return str(jwt.encode(payload, _secret(), algorithm=_algorithm()))


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(token, _secret(), algorithms=[_algorithm()])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── Dependencies ───────────────────────────────────────────────────────────────


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
    """
    Decode the bearer token and return the user row from the DB.
    Raises 401 if token is invalid, expired, or user is inactive.
    """
    from app.auth.db import get_user_by_id
    from app.main import get_db  # imported here to avoid circular at module load

    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = int(payload["sub"])

    async for conn in get_db():
        user = await get_user_by_id(conn, user_id)
        if user is None or not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        return dict(user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials"
    )


def require_role(*roles: str) -> Any:
    """Returns a FastAPI dependency that enforces the caller has one of the given roles."""

    async def _check(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(roles)}",
            )
        return current_user

    return _check
