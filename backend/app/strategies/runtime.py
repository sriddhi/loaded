"""
Saved-strategy runtime — modes, paper-gated execution, and the scheduler.

Each strategy runs in one of three modes (set per strategy):
- `backtest` — run its backtest(s) on the configured timeframes.
- `signal`   — compute today's BUY/SELL/HOLD signal and log it.
- `paper`    — compute the signal and, if actionable, place a PAPER order, while
               also keeping the backtest validation running.

SAFETY: paper mode places orders ONLY on the Alpaca paper account, behind
`alpaca_configured(paper=True)`. It never touches a live account. Strategies are
disabled by default; the scheduler only runs enabled ones whose schedule is due.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
from app.ops.metrics import track_job
from app.strategies.backtest import _record_run, run_backtests
from app.strategies.evaluator import _fetch_ohlcv, _generate_signals
from app.strategies.models import StrategyConfig

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def latest_signal(config: StrategyConfig, symbol: str, period: str = "3mo") -> str:
    """Compute the most recent BUY / SELL / HOLD for a strategy on a symbol."""
    df = _fetch_ohlcv(symbol, period)
    signals = _generate_signals(df, config)
    if len(signals) == 0:
        return "HOLD"
    last = int(signals.iloc[-1])
    return "BUY" if last == 1 else "SELL" if last == -1 else "HOLD"


def paper_enabled() -> bool:
    from app.alpaca.client import alpaca_configured

    return bool(alpaca_configured(paper=True))


def place_paper_order(symbol: str, side: str, qty: int) -> dict[str, Any]:
    """Place a market order on the Alpaca PAPER account. Refuses if not paper-configured.

    Returns a dict describing the outcome; never raises for the not-configured case.
    """
    if not paper_enabled():
        return {"placed": False, "reason": "paper trading not configured (no Alpaca paper keys)"}
    try:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        from app.alpaca.client import get_trading_client

        client = get_trading_client(paper=True)  # hard-locked to paper
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        return {"placed": True, "order_id": str(getattr(order, "id", "")), "side": side, "qty": qty}
    except Exception as exc:  # noqa: BLE001
        log.warning("[strategy-runtime] paper order failed: %s", exc)
        return {"placed": False, "reason": str(exc)}


def _strategy_symbol(strategy: dict[str, Any]) -> str:
    syms = strategy.get("symbols") or []
    if syms:
        return str(syms[0])
    rc = strategy.get("run_config") or {}
    return str(rc.get("backtest_symbol") or "SPY")


async def run_strategy_once(
    pool: asyncpg.Pool, strategy: dict[str, Any], *, source: str = "backend"
) -> dict[str, Any]:
    """Execute a strategy once according to its mode. Always logs a strategy_runs row."""
    mode = strategy.get("mode", "backtest")
    rc = strategy.get("run_config") or {}

    if mode == "backtest":
        periods = rc.get("backtest_periods") or ["1y"]
        results = await run_backtests(pool, strategy, periods, source=source)
        return {"mode": "backtest", "results": results}

    # signal / paper both need today's signal
    config = StrategyConfig(**strategy["config"])
    symbol = _strategy_symbol(strategy)
    start = time.monotonic()
    try:
        action = await asyncio.to_thread(latest_signal, config, symbol)
        detail: dict[str, Any] = {"symbol": symbol, "action": action}
        run_type = "signal"
        if mode == "paper":
            run_type = "paper"
            if action in ("BUY", "SELL"):
                order = await asyncio.to_thread(
                    place_paper_order, symbol, action, int(rc.get("paper_qty", 1))
                )
                detail["order"] = order
            else:
                detail["order"] = {"placed": False, "reason": "no actionable signal"}
        duration_ms = int((time.monotonic() - start) * 1000)
        async with pool.acquire() as conn:
            run_id = await _record_run(
                conn,
                strategy["id"],
                run_type=run_type,
                status="ok",
                source=source,
                period=None,
                metrics=detail,
                equity_curve=None,
                detail=action,
                duration_ms=duration_ms,
            )
        return {"mode": mode, "run_id": run_id, **detail}
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - start) * 1000)
        async with pool.acquire() as conn:
            await _record_run(
                conn,
                strategy["id"],
                run_type=mode,
                status="error",
                source=source,
                period=None,
                metrics=None,
                equity_curve=None,
                detail=str(exc),
                duration_ms=duration_ms,
            )
        return {"mode": mode, "status": "error", "detail": str(exc)}


def _is_due(strategy: dict[str, Any], now_utc: datetime) -> bool:
    """Decide whether an enabled strategy should run now, per its schedule."""
    rc = strategy.get("run_config") or {}
    kind = rc.get("schedule_kind", "manual")
    last = strategy.get("last_run_at")
    if kind == "manual":
        return False
    if kind == "once":
        # Run a single time (when it has never run), then never again.
        return last is None
    if kind == "interval":
        minutes = int(rc.get("interval_minutes", 60))
        if last is None:
            return True
        return bool((now_utc - last).total_seconds() >= minutes * 60)
    if kind == "daily":
        hhmm = str(rc.get("run_at_et", "16:05"))
        now_et = now_utc.astimezone(_ET)
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
        except ValueError:
            hh, mm = 16, 5
        if now_et.hour < hh or (now_et.hour == hh and now_et.minute < mm):
            return False
        # Run unless it already ran today (ET).
        return last is None or last.astimezone(_ET).date() != now_et.date()
    return False


class StrategyScheduler:
    """In-process loop: every minute, run enabled strategies whose schedule is due."""

    def __init__(self, pool: asyncpg.Pool, check_interval_seconds: int = 60) -> None:
        self._pool = pool
        self._interval = check_interval_seconds
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True

    async def _load_enabled(self) -> list[dict[str, Any]]:
        import json

        rows = await self._pool.fetch(
            "SELECT id, name, config_json, mode, symbols, run_config_json, last_run_at "
            "FROM strategies WHERE enabled = true"
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "config": json.loads(r["config_json"]),
                    "mode": r["mode"],
                    "symbols": list(r["symbols"]) if r["symbols"] else [],
                    "run_config": json.loads(r["run_config_json"]) if r["run_config_json"] else {},
                    "last_run_at": r["last_run_at"],
                }
            )
        return out

    async def _tick(self) -> int:
        now = datetime.now(UTC)
        ran = 0
        for strategy in await self._load_enabled():
            if _is_due(strategy, now):
                await run_strategy_once(self._pool, strategy, source="backend")
                ran += 1
        return ran

    async def run(self) -> None:
        log.info("[strategy-scheduler] started (checks every %ds)", self._interval)
        while not self._stopping:
            try:
                with track_job("strategy_scheduler", "backend"):
                    ran = await self._tick()
                if ran:
                    log.info("[strategy-scheduler] ran %d strategy(ies)", ran)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("[strategy-scheduler] tick error: %s", exc)
            for _ in range(self._interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)
