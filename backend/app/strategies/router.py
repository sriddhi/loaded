import json
import logging
from typing import Any

import anthropic
import asyncpg
from app.strategies.backtest import run_backtests
from app.strategies.chat import chat as run_chat
from app.strategies.chat import chat_enabled
from app.strategies.evaluator import evaluate_strategy
from app.strategies.generator import generate_strategy
from app.strategies.models import (
    BacktestRequest,
    ChatRequest,
    ChatResponse,
    EvalRequest,
    EvalResult,
    GenerateRequest,
    SaveStrategyRequest,
    StrategyConfig,
    UpdateStrategyRequest,
)
from fastapi import APIRouter, HTTPException, Request, status

log = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


def _row_to_strategy(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "config": json.loads(r["config_json"]),
        "mode": r["mode"],
        "enabled": r["enabled"],
        "symbols": list(r["symbols"]) if r["symbols"] else [],
        "run_config": json.loads(r["run_config_json"]) if r["run_config_json"] else {},
        "last_run_at": r["last_run_at"].isoformat() if r["last_run_at"] else None,
        "created_at": r["created_at"].isoformat(),
    }


_SELECT = (
    "SELECT id, name, config_json, mode, enabled, symbols, run_config_json, "
    "last_run_at, created_at FROM strategies"
)


# ── Generate / evaluate (existing) ────────────────────────────────────────────


@router.post("/generate", response_model=StrategyConfig)
async def generate(body: GenerateRequest) -> StrategyConfig:
    try:
        return generate_strategy(body.natural_language_prompt)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/evaluate", response_model=EvalResult)
async def evaluate(body: EvalRequest) -> EvalResult:
    try:
        return evaluate_strategy(
            config=body.strategy_config,
            symbol=body.symbol,
            period=body.period,
            initial_capital=body.initial_capital,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        log.error(f"Evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}") from e


# ── Chat (agentic builder) ────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    if not chat_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat unavailable — ANTHROPIC_API_KEY is not configured.",
        )
    try:
        return await run_chat(body.messages)
    except anthropic.APIError as e:
        log.error(f"Chat upstream (Anthropic) error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Assistant upstream error: {getattr(e, 'message', str(e))}",
        ) from e
    except Exception as e:  # noqa: BLE001
        log.error(f"Chat failed: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}") from e


# ── Saved strategies CRUD ─────────────────────────────────────────────────────


@router.get("/")
async def list_strategies(request: Request) -> list[dict[str, Any]]:
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(f"{_SELECT} ORDER BY created_at DESC")
    return [_row_to_strategy(r) for r in rows]


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: int, request: Request) -> dict[str, Any]:
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(f"{_SELECT} WHERE id = $1", strategy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        runs = await conn.fetch(
            "SELECT id, run_type, status, source, period, metrics_json, detail, "
            "duration_ms, created_at FROM strategy_runs WHERE strategy_id = $1 "
            "ORDER BY created_at DESC LIMIT 20",
            strategy_id,
        )
    out = _row_to_strategy(row)
    out["recent_runs"] = [_row_to_run(r) for r in runs]
    return out


@router.post("/save")
async def save_strategy(body: SaveStrategyRequest, request: Request) -> dict[str, Any]:
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO strategies (name, config_json, mode, enabled, symbols, run_config_json)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, name, config_json, mode, enabled, symbols, run_config_json,
                      last_run_at, created_at
            """,
            body.config.name,
            body.config.model_dump_json(),
            body.mode,
            body.enabled,
            body.symbols,
            body.run_config.model_dump_json(),
        )
    return _row_to_strategy(row)


@router.patch("/{strategy_id}")
async def update_strategy(
    strategy_id: int, body: UpdateStrategyRequest, request: Request
) -> dict[str, Any]:
    sets: list[str] = ["updated_at = NOW()"]
    args: list[Any] = []
    if body.config is not None:
        args.append(body.config.model_dump_json())
        sets.append(f"config_json = ${len(args)}")
        args.append(body.config.name)
        sets.append(f"name = ${len(args)}")
    if body.mode is not None:
        args.append(body.mode)
        sets.append(f"mode = ${len(args)}")
    if body.enabled is not None:
        args.append(body.enabled)
        sets.append(f"enabled = ${len(args)}")
    if body.symbols is not None:
        args.append(body.symbols)
        sets.append(f"symbols = ${len(args)}")
    if body.run_config is not None:
        args.append(body.run_config.model_dump_json())
        sets.append(f"run_config_json = ${len(args)}")
    args.append(strategy_id)
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE strategies SET {', '.join(sets)} WHERE id = ${len(args)} "
            f"RETURNING id, name, config_json, mode, enabled, symbols, run_config_json, "
            f"last_run_at, created_at",
            *args,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _row_to_strategy(row)


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: int, request: Request) -> dict[str, bool]:
    async with _pool(request).acquire() as conn:
        result = await conn.execute("DELETE FROM strategies WHERE id = $1", strategy_id)
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {"deleted": True}


# ── Backtest + run history ────────────────────────────────────────────────────


def _row_to_run(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": r["id"],
        "run_type": r["run_type"],
        "status": r["status"],
        "source": r["source"],
        "period": r["period"],
        "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else None,
        "detail": r["detail"],
        "duration_ms": r["duration_ms"],
        "created_at": r["created_at"].isoformat(),
    }


@router.post("/{strategy_id}/backtest")
async def backtest_strategy(
    strategy_id: int, body: BacktestRequest, request: Request
) -> dict[str, Any]:
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(f"{_SELECT} WHERE id = $1", strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy = _row_to_strategy(row)
    results = await run_backtests(
        _pool(request),
        strategy,
        body.periods,
        symbol=body.symbol,
        initial_capital=body.initial_capital,
        source="ui",
    )
    return {"strategy_id": strategy_id, "results": results}


@router.get("/{strategy_id}/runs")
async def list_runs(strategy_id: int, request: Request) -> list[dict[str, Any]]:
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, run_type, status, source, period, metrics_json, detail, "
            "duration_ms, created_at FROM strategy_runs WHERE strategy_id = $1 "
            "ORDER BY created_at DESC LIMIT 50",
            strategy_id,
        )
    return [_row_to_run(r) for r in rows]
