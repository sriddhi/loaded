import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.strategies.evaluator import evaluate_strategy
from app.strategies.generator import generate_strategy
from app.strategies.models import EvalRequest, EvalResult, GenerateRequest, StrategyConfig

log = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["strategies"])


async def get_db(request: Request) -> asyncpg.Connection:
    conn = await asyncpg.connect(request.app.state.db_url)
    try:
        yield conn
    finally:
        await conn.close()


@router.post("/generate", response_model=StrategyConfig)
async def generate(body: GenerateRequest):
    try:
        return generate_strategy(body.natural_language_prompt)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evaluate", response_model=EvalResult)
async def evaluate(body: EvalRequest):
    try:
        return evaluate_strategy(
            config=body.strategy_config,
            symbol=body.symbol,
            period=body.period,
            initial_capital=body.initial_capital,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.error(f"Evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")


@router.get("/")
async def list_strategies(request: Request):
    conn = await asyncpg.connect(request.app.state.db_url)
    try:
        rows = await conn.fetch("SELECT id, name, config_json, created_at FROM strategies ORDER BY created_at DESC")
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "config": json.loads(r["config_json"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    finally:
        await conn.close()


@router.post("/save")
async def save_strategy(body: StrategyConfig, request: Request):
    conn = await asyncpg.connect(request.app.state.db_url)
    try:
        row = await conn.fetchrow(
            "INSERT INTO strategies (name, config_json) VALUES ($1, $2) RETURNING id, created_at",
            body.name,
            body.model_dump_json(),
        )
        return {
            "id": row["id"],
            "name": body.name,
            "config": body.model_dump(),
            "created_at": row["created_at"].isoformat(),
        }
    finally:
        await conn.close()
