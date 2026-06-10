"""
Finnhub websocket consumer — streams live US-equity trade prices into a PriceStore.

Free tier: US trades only, ≤50 symbols, wss://ws.finnhub.io?token=KEY.
Subscribe with {"type":"subscribe","symbol":"AAPL"}; trade messages look like
{"type":"trade","data":[{"s":sym,"p":price,"t":epoch_ms,"v":vol}]}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import websockets
from app.fundamentals.price_cache import PriceStore

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.finnhub.io"
FREE_TIER_SYMBOL_CAP = 50


def finnhub_api_key() -> str:
    return os.getenv("FINNHUB_API_KEY", "")


def finnhub_ws_enabled() -> bool:
    return bool(finnhub_api_key())


class FinnhubWsClient:
    def __init__(self, api_key: str, cache: PriceStore, symbols: list[str]) -> None:
        self._api_key = api_key
        self._cache = cache
        self._symbols = [s.upper() for s in symbols]
        self._stopping = False
        self.connected = False

    async def stop(self) -> None:
        self._stopping = True

    def _subscribe_set(self) -> list[str]:
        if len(self._symbols) > FREE_TIER_SYMBOL_CAP:
            logger.warning(
                "[finnhub] %d tracked symbols exceeds free-tier cap %d; subscribing to first %d",
                len(self._symbols),
                FREE_TIER_SYMBOL_CAP,
                FREE_TIER_SYMBOL_CAP,
            )
        return self._symbols[:FREE_TIER_SYMBOL_CAP]

    def handle_message(self, raw: str) -> None:
        """Parse a websocket message and update the price cache (trades only)."""
        msg = json.loads(raw)
        if msg.get("type") == "trade":
            for t in msg.get("data", []):
                self._cache.update(str(t["s"]), float(t["p"]), int(t["t"]))

    async def run(self) -> None:
        url = f"{WS_URL}?token={self._api_key}"
        attempt = 0
        while not self._stopping:
            try:
                async with websockets.connect(url) as ws:
                    self.connected = True
                    for sym in self._subscribe_set():
                        await ws.send(json.dumps({"type": "subscribe", "symbol": sym}))
                    logger.info("[finnhub] ws connected, %d symbols", len(self._subscribe_set()))
                    attempt = 0
                    async for raw in ws:
                        self.handle_message(raw if isinstance(raw, str) else raw.decode())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — reconnect on any ws error
                logger.warning("[finnhub] ws error: %s", exc)
            finally:
                self.connected = False
            if self._stopping:
                break
            await asyncio.sleep(min(60, 2**attempt))
            attempt += 1
