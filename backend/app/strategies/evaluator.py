"""
Vectorized backtest engine. Evaluates a StrategyConfig against historical OHLCV data.
"""
import logging
from datetime import datetime, timezone
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf

from app.strategies.models import EvalResult, StrategyConfig, TradeSignal

log = logging.getLogger(__name__)

RISK_FREE_RATE = 0.04
TRADING_DAYS = 252


def _fetch_ohlcv(symbol: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"No OHLCV data returned for {symbol} / {period}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    return df


def _generate_signals(df: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    """
    Generate a signal series (+1 = buy, -1 = sell, 0 = hold) based on strategy type.
    Uses only the parameters defined in config.parameters.
    """
    params = config.parameters
    close = df["close"]
    volume = df["volume"]

    if config.type.value in ("MOMENTUM", "BREAKOUT"):
        sma_period = int(params.get("sma_period", 20))
        vol_mult = float(params.get("volume_multiplier", 1.5))

        sma = close.rolling(sma_period).mean()
        avg_vol = volume.rolling(sma_period).mean()

        above_sma = close > sma
        high_volume = volume > (avg_vol * vol_mult)

        # Entry: price crosses above SMA on high volume
        cross_up = above_sma & ~above_sma.shift(1).fillna(False) & high_volume
        # Exit: price crosses below SMA
        cross_down = ~above_sma & above_sma.shift(1).fillna(False)

        signal = pd.Series(0, index=df.index)
        signal[cross_up] = 1
        signal[cross_down] = -1

    elif config.type.value == "MEAN_REVERSION":
        period = int(params.get("sma_period", 20))
        std_mult = float(params.get("std_multiplier", 2.0))

        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        lower_band = sma - std_mult * std
        upper_band = sma + std_mult * std

        # Entry: price below lower band (oversold)
        cross_up = (close < lower_band) & (close.shift(1) >= lower_band.shift(1))
        # Exit: price above upper band or mean
        cross_down = close > sma

        signal = pd.Series(0, index=df.index)
        signal[cross_up] = 1
        signal[cross_down] = -1

    else:
        # CUSTOM: fall back to simple SMA crossover
        sma_period = int(params.get("sma_period", 20))
        sma = close.rolling(sma_period).mean()
        above = close > sma
        signal = pd.Series(0, index=df.index)
        signal[above & ~above.shift(1).fillna(False)] = 1
        signal[~above & above.shift(1).fillna(False)] = -1

    return signal


def _apply_filters(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    filters = config.filters
    if "min_price" in filters:
        df = df[df["close"] >= float(filters["min_price"])]
    if "min_avg_volume" in filters:
        avg_vol = df["volume"].rolling(20).mean()
        df = df[avg_vol >= float(filters["min_avg_volume"])]
    return df


def _run_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    initial_capital: float,
) -> tuple[List[float], List[TradeSignal]]:
    """
    Simulate trades. Enter on next open after signal bar. No fractional shares, no shorting.
    Returns (equity_curve, trade_signals).
    """
    equity = initial_capital
    position = 0  # shares held
    entry_price = 0.0
    equity_curve = []
    trade_signals = []

    opens = df["open"].values
    closes = df["close"].values
    dates = df.index
    sig = signals.reindex(df.index).fillna(0).values

    for i in range(len(df)):
        # Execute on next open after signal (i-1 signal → i open)
        if i > 0:
            prev_sig = sig[i - 1]
            open_price = opens[i]

            if prev_sig == 1 and position == 0:
                # Buy — invest all capital
                shares = int(equity / open_price)
                if shares > 0:
                    position = shares
                    entry_price = open_price
                    equity -= shares * open_price
                    trade_signals.append(TradeSignal(
                        date=str(dates[i].date()),
                        action="BUY",
                        price=round(open_price, 4),
                    ))

            elif prev_sig == -1 and position > 0:
                # Sell
                proceeds = position * open_price
                pnl = round(proceeds - position * entry_price, 4)
                equity += proceeds
                trade_signals.append(TradeSignal(
                    date=str(dates[i].date()),
                    action="SELL",
                    price=round(open_price, 4),
                    pnl=pnl,
                ))
                position = 0
                entry_price = 0.0

        # Daily equity = cash + mark-to-market
        current_equity = equity + position * closes[i]
        equity_curve.append(round(current_equity, 4))

    # Close any open position at last close
    if position > 0:
        final_price = closes[-1]
        pnl = round(position * final_price - position * entry_price, 4)
        equity += position * final_price
        trade_signals.append(TradeSignal(
            date=str(dates[-1].date()),
            action="SELL",
            price=round(final_price, 4),
            pnl=pnl,
        ))
        equity_curve[-1] = round(equity, 4)

    return equity_curve, trade_signals


def _compute_metrics(
    equity_curve: List[float],
    trade_signals: List[TradeSignal],
    initial_capital: float,
) -> dict:
    if not equity_curve:
        return dict(
            total_return_pct=0.0, sharpe_ratio=0.0,
            max_drawdown_pct=0.0, win_rate=0.0, total_trades=0,
        )

    final_equity = equity_curve[-1]
    total_return_pct = round((final_equity - initial_capital) / initial_capital * 100, 4)

    # Sharpe ratio
    curve = np.array(equity_curve)
    daily_returns = np.diff(curve) / curve[:-1]
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        excess = daily_returns - (RISK_FREE_RATE / TRADING_DAYS)
        sharpe = round(float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS)), 4)
    else:
        sharpe = 0.0

    # Max drawdown
    peak = np.maximum.accumulate(curve)
    drawdowns = (curve - peak) / np.where(peak == 0, 1, peak) * 100
    max_drawdown_pct = round(float(drawdowns.min()), 4)

    # Win rate — based on completed round trips (pairs of BUY/SELL)
    sells = [s for s in trade_signals if s.action == "SELL" and s.pnl is not None]
    total_trades = len(sells)
    if total_trades > 0:
        wins = sum(1 for s in sells if s.pnl > 0)
        win_rate = round(wins / total_trades * 100, 4)
    else:
        win_rate = 0.0

    return dict(
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        total_trades=total_trades,
    )


def evaluate_strategy(
    config: StrategyConfig,
    symbol: str,
    period: str,
    initial_capital: float,
) -> EvalResult:
    try:
        df = _fetch_ohlcv(symbol, period)
    except Exception as e:
        raise ValueError(f"Could not fetch market data for '{symbol}' ({period}): {e}") from e

    df = _apply_filters(df, config)

    if df.empty:
        return EvalResult(
            strategy_name=config.name,
            symbol=symbol,
            period=period,
            total_return_pct=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate=0.0,
            total_trades=0,
            equity_curve=[initial_capital] * 2,
            signals=[],
        )

    signals = _generate_signals(df, config)
    equity_curve, trade_signals = _run_backtest(df, signals, initial_capital)
    metrics = _compute_metrics(equity_curve, trade_signals, initial_capital)

    return EvalResult(
        strategy_name=config.name,
        symbol=symbol,
        period=period,
        equity_curve=equity_curve,
        signals=trade_signals,
        generated_at=datetime.now(timezone.utc),
        **metrics,
    )
