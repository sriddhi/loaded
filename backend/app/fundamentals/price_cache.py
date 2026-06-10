"""
Latest-price cache for the Finnhub websocket.

In-memory (single backend instance in dev). Dict reads/writes are atomic under the
single event loop, so no lock is needed. The `PriceStore` Protocol lets a
Redis-backed implementation drop in later for horizontal scaling.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PriceStore(Protocol):
    def update(self, symbol: str, price: float, ts_ms: int) -> None: ...
    def get(self, symbol: str) -> tuple[float, int] | None: ...


class InMemoryPriceCache:
    def __init__(self) -> None:
        self._prices: dict[str, tuple[float, int]] = {}

    def update(self, symbol: str, price: float, ts_ms: int) -> None:
        self._prices[symbol.upper()] = (price, ts_ms)

    def get(self, symbol: str) -> tuple[float, int] | None:
        return self._prices.get(symbol.upper())

    def __len__(self) -> int:
        return len(self._prices)
