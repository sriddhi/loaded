"""
Signal backtester — a separate job that validates each past signal once its
horizon has elapsed.

Every signal carries an implicit *price thesis* (bullish → up, bearish → down,
bull_trap → reverses down, bear_trap → reverses up, neutral → stays flat). Once
`signal_ts + horizon` is in the past, we compare the signal's price against the
actually-recorded price at/after that target time (the engine records a row every
minute, so the realized price is already in `spy_signals`) and mark the rating
`correct` or `wrong`. The thesis itself is never surfaced — only the verdict.

Results are written back to the originating row (`res_5m/res_10m/res_20m/res_1d`)
so the UI can show a ✓/✗ next to each rating and compute a hit-rate.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import asyncpg
from app.ops.metrics import track_job
from app.signals.engine import HORIZONS, _threshold

logger = logging.getLogger(__name__)

# horizon_min → (signal-label column, result column)
_COLS: dict[int, tuple[str, str]] = {
    1: ("sig_1m", "res_1m"),
    5: ("sig_5m", "res_5m"),
    10: ("sig_10m", "res_10m"),
    20: ("sig_20m", "res_20m"),
    1440: ("sig_1d", "res_1d"),
}


def judge(label: str, price_then: float, price_after: float, horizon_min: int) -> str:
    """Was the thesis right? Returns 'correct' or 'wrong'.

    The thesis is directional and never shown; this only emits the verdict.
    """
    if price_then <= 0:
        return "wrong"
    ret = (price_after - price_then) / price_then
    thr = _threshold(horizon_min)
    if label == "bullish":
        hit = ret > 0
    elif label == "bearish" or label == "bull_trap":
        hit = ret < 0
    elif label == "bear_trap":  # failed breakdown → expect upside
        hit = ret > 0
    elif label == "neutral":  # expect to stay within the band
        hit = abs(ret) <= thr
    else:
        hit = False
    return "correct" if hit else "wrong"


async def evaluate_due(pool: asyncpg.Pool, batch: int = 500) -> int:
    """Validate every signal whose horizon has elapsed and isn't yet judged.

    Returns the number of ratings resolved this pass.
    """
    resolved = 0
    async with pool.acquire() as conn:
        for horizon in HORIZONS:
            sig_col, res_col = _COLS[horizon]
            due = await conn.fetch(
                f"""
                SELECT id, symbol, ts, price, {sig_col} AS label
                FROM spy_signals
                WHERE {res_col} IS NULL
                  AND {sig_col} IS NOT NULL
                  AND ts <= NOW() - make_interval(mins => $1)
                ORDER BY ts ASC
                LIMIT $2
                """,
                horizon,
                batch,
            )
            for row in due:
                target = row["ts"] + timedelta(minutes=horizon)
                fut = await conn.fetchrow(
                    "SELECT price FROM spy_signals "
                    "WHERE symbol = $1 AND ts >= $2 ORDER BY ts ASC LIMIT 1",
                    row["symbol"],
                    target,
                )
                if fut is None:
                    # No realized price recorded at/after the target yet — leave pending.
                    continue
                outcome = judge(row["label"], float(row["price"]), float(fut["price"]), horizon)
                await conn.execute(
                    f"UPDATE spy_signals SET {res_col} = $1 WHERE id = $2", outcome, row["id"]
                )
                resolved += 1
    return resolved


# ── Background job ────────────────────────────────────────────────────────────


class BacktestJob:
    """Runs `evaluate_due` on a fixed cadence (default 60s)."""

    def __init__(self, pool: asyncpg.Pool, interval_seconds: int = 60) -> None:
        self._pool = pool
        self._interval = interval_seconds
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        logger.info("[backtest] signal backtester started (every %ds)", self._interval)
        while not self._stopping:
            try:
                with track_job("signal_backtester", "backend"):
                    n = await evaluate_due(self._pool)
                if n:
                    logger.info("[backtest] resolved %d signal(s)", n)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[backtest] evaluate error: %s", exc)
            for _ in range(self._interval):
                if self._stopping:
                    return
                await asyncio.sleep(1)


def accuracy_summary(rows: list[dict[str, Any]]) -> dict[int, dict[str, int]]:
    """Aggregate hit/total per horizon from a list of signal dicts (for tests)."""
    out: dict[int, dict[str, int]] = {h: {"hits": 0, "total": 0} for h in HORIZONS}
    for row in rows:
        for sig in row.get("signals", []):
            h = sig["horizon_min"]
            outcome = sig.get("outcome", "pending")
            if outcome in ("correct", "wrong"):
                out[h]["total"] += 1
                if outcome == "correct":
                    out[h]["hits"] += 1
    return out
