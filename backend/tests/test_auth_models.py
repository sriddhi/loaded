"""
Unit tests for auth/models.py — Pydantic schema validation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.auth.models import RefreshRequest, TokenResponse, UserCreate, UserOut, UserUpdate
from pydantic import ValidationError


def test_user_create_valid():
    u = UserCreate(email="user@example.com", password="securepass")
    assert u.email == "user@example.com"
    assert u.role == "client"


def test_user_create_defaults_role_to_client():
    u = UserCreate(email="a@b.com", password="password1")
    assert u.role == "client"


def test_user_create_accepts_admin_role():
    u = UserCreate(email="a@b.com", password="password1", role="admin")
    assert u.role == "admin"


def test_user_create_password_too_short():
    with pytest.raises(ValidationError, match="at least 8"):
        UserCreate(email="a@b.com", password="short")


def test_user_create_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="securepass")


def test_user_out_fields():
    now = datetime.now(UTC)
    u = UserOut(id=1, email="a@b.com", role="admin", is_active=True, created_at=now)
    assert u.id == 1
    assert u.role == "admin"


def test_token_response_defaults():
    t = TokenResponse(access_token="abc", refresh_token="xyz")
    assert t.token_type == "bearer"


def test_refresh_request():
    r = RefreshRequest(refresh_token="mytoken")
    assert r.refresh_token == "mytoken"


def test_user_update_all_none():
    u = UserUpdate()
    assert u.role is None
    assert u.is_active is None


def test_user_update_partial():
    u = UserUpdate(role="ops")
    assert u.role == "ops"
    assert u.is_active is None


def test_user_update_invalid_role():
    with pytest.raises(ValidationError):
        UserUpdate(role="superadmin")
