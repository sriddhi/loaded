"""
Unit tests for auth/security.py — password hashing and JWT logic.
No DB or network required.
"""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

os.environ.setdefault(
    "JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-testing-purposes-only"
)

from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_round_trip():
    hashed = hash_password("mysecretpass")
    assert verify_password("mysecretpass", hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("correctpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_create_access_token_payload():
    token = create_access_token(user_id=42, role="admin")
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_create_refresh_token_payload():
    token = create_refresh_token(user_id=7)
    payload = decode_token(token)
    assert payload["sub"] == "7"
    assert payload["type"] == "refresh"


def test_decode_tampered_token_raises_401():
    token = create_access_token(user_id=1, role="client")
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(HTTPException) as exc_info:
        decode_token(tampered)
    assert exc_info.value.status_code == 401


def test_decode_token_wrong_secret_raises_401():
    token = create_access_token(user_id=1, role="client")
    with patch.dict(os.environ, {"JWT_SECRET_KEY": "completely-different-secret-key-value-here"}):
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401


def test_missing_jwt_secret_raises_runtime_error():
    with (
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(RuntimeError, match="JWT_SECRET_KEY"),
    ):
        from app.auth import security

        security._secret()
