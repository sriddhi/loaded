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


# ── Strategy Lab: execution + chat ────────────────────────────────────────────

StrategyMode = str  # "backtest" | "signal" | "paper"


class RunConfig(BaseModel):
    """Per-strategy execution + schedule settings (stored as run_config_json)."""

    schedule_kind: str = "manual"  # manual | interval | daily
    interval_minutes: int = 60
    run_at_et: str = "16:05"  # for daily, HH:MM US/Eastern
    backtest_enabled: bool = True
    backtest_periods: list[str] = Field(default_factory=lambda: ["1y"])
    backtest_symbol: str | None = None
    paper_qty: int = 1
    max_positions: int = 1


class SaveStrategyRequest(BaseModel):
    config: StrategyConfig
    mode: StrategyMode = "backtest"
    enabled: bool = False
    symbols: list[str] = Field(default_factory=list)
    run_config: RunConfig = Field(default_factory=RunConfig)


class UpdateStrategyRequest(BaseModel):
    config: StrategyConfig | None = None
    mode: StrategyMode | None = None
    enabled: bool | None = None
    symbols: list[str] | None = None
    run_config: RunConfig | None = None


class BacktestRequest(BaseModel):
    periods: list[str] = Field(default_factory=lambda: ["1y"])
    symbol: str | None = None
    initial_capital: float = 10000.0


class ChatMessage(BaseModel):
    role: str  # user | assistant
    content: Any  # str, or a list of content blocks (tool use/result)


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class Artifact(BaseModel):
    type: str  # strategy | market_data | backtest | text
    data: Any = None


class ChatResponse(BaseModel):
    reply: str
    messages: list[ChatMessage]
    artifact: Artifact
