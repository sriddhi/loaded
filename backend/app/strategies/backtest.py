"""
Strategy backtest-run framework — runs a saved strategy's backtest (on demand or
scheduled), across one or more timeframes, and persists each result to
`strategy_runs` for history + the per-strategy observability view.

Reuses the existing vectorized engine (`evaluator.evaluate_strategy`).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import asyncpg
from app.strategies.evaluator import evaluate_strategy
from app.strategies.models import StrategyConfig

log = logging.getLogger(__name__)


def _default_symbol(strategy: dict[str, Any], override: str | None) -> str:
    if override:
        return override
    syms = strategy.get("symbols") or []
    if syms:
        return str(syms[0])
    rc = strategy.get("run_config") or {}
    return str(rc.get("backtest_symbol") or "SPY")


async def _record_run(
    conn: asyncpg.Connection,
    strategy_id: int,
    *,
    run_type: str,
    status: str,
    source: str,
    period: str | None,
    metrics: dict[str, Any] | None,
    equity_curve: list[float] | None,
    detail: str | None,
    duration_ms: int,
) -> int:
    run_id: int = await conn.fetchval(
        """
        INSERT INTO strategy_runs
            (strategy_id, run_type, status, source, period, metrics_json,
             equity_curve_json, detail, duration_ms)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        strategy_id,
        run_type,
        status,
        source,
        period,
        json.dumps(metrics) if metrics is not None else None,
        json.dumps(equity_curve) if equity_curve is not None else None,
        detail,
        duration_ms,
    )
    await conn.execute("UPDATE strategies SET last_run_at = NOW() WHERE id = $1", strategy_id)
    return run_id


async def run_backtest_for(
    pool: asyncpg.Pool,
    strategy: dict[str, Any],
    period: str,
    *,
    symbol: str | None = None,
    initial_capital: float = 10000.0,
    source: str = "backend",
) -> dict[str, Any]:
    """Run one backtest period for a saved strategy and persist it. Never raises."""
    config = StrategyConfig(**strategy["config"])
    sym = _default_symbol(strategy, symbol)
    start = time.monotonic()
    try:
        result = evaluate_strategy(
            config=config, symbol=sym, period=period, initial_capital=initial_capital
        )
        metrics = {
            "symbol": sym,
            "total_return_pct": result.total_return_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
        }
        duration_ms = int((time.monotonic() - start) * 1000)
        async with pool.acquire() as conn:
            run_id = await _record_run(
                conn,
                strategy["id"],
                run_type="backtest",
                status="ok",
                source=source,
                period=period,
                metrics=metrics,
                equity_curve=result.equity_curve,
                detail=None,
                duration_ms=duration_ms,
            )
        return {
            "run_id": run_id,
            "status": "ok",
            "period": period,
            "metrics": metrics,
            "equity_curve": result.equity_curve,
            "signals": [s.model_dump() for s in result.signals],
        }
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - start) * 1000)
        log.warning("[strategy-backtest] %s / %s failed: %s", strategy.get("id"), period, exc)
        async with pool.acquire() as conn:
            run_id = await _record_run(
                conn,
                strategy["id"],
                run_type="backtest",
                status="error",
                source=source,
                period=period,
                metrics=None,
                equity_curve=None,
                detail=str(exc),
                duration_ms=duration_ms,
            )
        return {"run_id": run_id, "status": "error", "period": period, "detail": str(exc)}


async def run_backtests(
    pool: asyncpg.Pool,
    strategy: dict[str, Any],
    periods: list[str],
    *,
    symbol: str | None = None,
    initial_capital: float = 10000.0,
    source: str = "backend",
) -> list[dict[str, Any]]:
    """Run a backtest for each requested period."""
    out: list[dict[str, Any]] = []
    for period in periods:
        out.append(
            await run_backtest_for(
                pool,
                strategy,
                period,
                symbol=symbol,
                initial_capital=initial_capital,
                source=source,
            )
        )
    return out
