"""
Pydantic models for auth requests and responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: Literal["admin", "client", "ops"] = "client"

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    auth_provider: str | None = None
    settings: dict[str, Any] = {}


class SettingsUpdate(BaseModel):
    """Partial settings to merge into the user's stored settings."""

    settings: dict[str, Any]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class UserUpdate(BaseModel):
    role: Literal["admin", "client", "ops"] | None = None
    is_active: bool | None = None
