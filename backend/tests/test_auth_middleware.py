"""
Unit tests for auth/middleware.py — DocsAuthMiddleware.
"""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-that-is-long-enough-for-testing-purposes-only",
)

from app.auth.middleware import DocsAuthMiddleware, _extract_bearer  # noqa: E402
from app.auth.security import create_access_token  # noqa: E402

# ── _extract_bearer ────────────────────────────────────────────────────────────


def _mock_request(auth_header: str | None = None) -> Request:
    headers = {}
    if auth_header:
        headers["authorization"] = auth_header
    scope = {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


def test_extract_bearer_with_valid_header():
    req = _mock_request("Bearer mytoken123")
    assert _extract_bearer(req) == "mytoken123"


def test_extract_bearer_with_no_header():
    req = _mock_request()
    assert _extract_bearer(req) is None


def test_extract_bearer_with_basic_auth():
    req = _mock_request("Basic dXNlcjpwYXNz")
    assert _extract_bearer(req) is None


# ── DocsAuthMiddleware via mini ASGI app ───────────────────────────────────────


def _make_app(path: str = "/docs") -> TestClient:
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def homepage(request: Request) -> Response:
        return Response("OK", status_code=200)

    app = Starlette(routes=[Route(path, homepage)])
    app.add_middleware(DocsAuthMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_docs_no_token_returns_401():
    c = _make_app("/docs")
    resp = c.get("/docs")
    assert resp.status_code == 401


def test_redoc_no_token_returns_401():
    c = _make_app("/redoc")
    resp = c.get("/redoc")
    assert resp.status_code == 401


def test_openapi_json_no_token_returns_401():
    c = _make_app("/openapi.json")
    resp = c.get("/openapi.json")
    assert resp.status_code == 401


def test_docs_client_token_returns_403():
    token = create_access_token(2, "client")
    c = _make_app("/docs")
    resp = c.get("/docs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_docs_admin_token_returns_200():
    token = create_access_token(1, "admin")
    c = _make_app("/docs")
    resp = c.get("/docs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_non_protected_path_passes_through():
    c = _make_app("/health")
    resp = c.get("/health")
    assert resp.status_code == 200


def test_invalid_token_returns_401():
    c = _make_app("/docs")
    resp = c.get("/docs", headers={"Authorization": "Bearer totally.invalid.token"})
    assert resp.status_code == 401
