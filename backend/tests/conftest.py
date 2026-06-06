"""
Shared pytest fixtures and test configuration.

Sets JWT_SECRET_KEY before any app code imports, and installs a
get_current_user override so existing non-auth tests don't need tokens.
"""

import os

# Must be set before any app module is imported
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-that-is-long-enough-for-testing-purposes-only",
)

import pytest  # noqa: E402
from app.auth.security import get_current_user  # noqa: E402
from app.main import app  # noqa: E402

_MOCK_ADMIN = {
    "id": 1,
    "email": "admin@loaded.app",
    "role": "admin",
    "is_active": True,
}


async def _override_get_current_user() -> dict:
    return _MOCK_ADMIN


@pytest.fixture(autouse=True)
def bypass_auth():
    """
    Override get_current_user for all tests so non-auth tests don't need tokens.
    Tests that need real auth behavior should use the `real_auth` fixture.
    """
    app.dependency_overrides[get_current_user] = _override_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def real_auth(bypass_auth):  # noqa: ARG001
    """
    Remove the bypass so get_current_user runs for real.
    Use in auth router tests that verify token/role enforcement.
    """
    app.dependency_overrides.pop(get_current_user, None)
    yield
    # bypass_auth teardown restores state
