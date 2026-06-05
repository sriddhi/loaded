from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StrategyType(str, Enum):
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    MEAN_REVERSION = "MEAN_REVERSION"
    CUSTOM = "CUSTOM"


class StrategyConfig(BaseModel):
    name: str
    description: str
    type: StrategyType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    filters: Dict[str, Any] = Field(default_factory=dict)
    signal_logic: str


class GenerateRequest(BaseModel):
    natural_language_prompt: str
    context: Optional[Dict[str, Any]] = None


class EvalRequest(BaseModel):
    strategy_config: StrategyConfig
    symbol: str
    period: str = "1y"
    initial_capital: float = 10000.0


class TradeSignal(BaseModel):
    date: str
    action: str  # BUY or SELL
    price: float
    pnl: Optional[float] = None


class EvalResult(BaseModel):
    strategy_name: str
    symbol: str
    period: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    equity_curve: List[float]
    signals: List[TradeSignal]
    generated_at: datetime = Field(default_factory=datetime.utcnow)
