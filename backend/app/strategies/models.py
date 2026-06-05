from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class StrategyType(StrEnum):
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    MEAN_REVERSION = "MEAN_REVERSION"
    CUSTOM = "CUSTOM"


class StrategyConfig(BaseModel):
    name: str
    description: str
    type: StrategyType
    parameters: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    signal_logic: str


class GenerateRequest(BaseModel):
    natural_language_prompt: str
    context: dict[str, Any] | None = None


class EvalRequest(BaseModel):
    strategy_config: StrategyConfig
    symbol: str
    period: str = "1y"
    initial_capital: float = 10000.0


class TradeSignal(BaseModel):
    date: str
    action: str  # BUY or SELL
    price: float
    pnl: float | None = None


class EvalResult(BaseModel):
    strategy_name: str
    symbol: str
    period: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    equity_curve: list[float]
    signals: list[TradeSignal]
    generated_at: datetime = Field(default_factory=datetime.utcnow)
