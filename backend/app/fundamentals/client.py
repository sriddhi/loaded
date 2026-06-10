"""Finnhub health shim for the /health endpoint."""

from __future__ import annotations

from app.fundamentals.finnhub_ws import FinnhubWsClient, finnhub_ws_enabled


def finnhub_ok(client: FinnhubWsClient | None) -> tuple[bool, str | None]:
    """Report Finnhub websocket health without making a network call."""
    if not finnhub_ws_enabled():
        return False, "missing_credentials"
    if client is None:
        return False, "not_started"
    if client.connected:
        return True, None
    return False, "connecting"
