"""
Middleware to protect /docs, /redoc, and /openapi.json behind admin-only JWT auth.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

PROTECTED_PATHS = {"/docs", "/redoc", "/openapi.json"}


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


class DocsAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in PROTECTED_PATHS:
            token = _extract_bearer(request)
            if not token:
                return Response("Unauthorized", status_code=401)
            try:
                from app.auth.security import decode_token

                payload = decode_token(token)
                if payload.get("type") != "access":
                    return Response("Unauthorized", status_code=401)
                if payload.get("role") != "admin":
                    return Response("Forbidden — admin access only", status_code=403)
            except Exception:
                return Response("Unauthorized", status_code=401)
        return await call_next(request)
