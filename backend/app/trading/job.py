"""
Async trading job — Opening Range Breakout on SPY options.

Runs every 5 minutes during market hours (09:30–16:00 ET).
Uses httpx.AsyncClient for all Alpaca HTTP calls (paper trading only).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx
from app.trading.state import (
    OpenPosition,
    ORBLevels,
    log_error,
    log_event,
    state_lock,
    trading_state,
)
from app.trading.strategy import (
    compute_orb,
    format_contract_symbol,
    select_strike,
    should_enter,
    should_exit,
    size_position,
)

logger = logging.getLogger(__name__)

# ── ET offset (UTC-4 during EDT, UTC-5 during EST) ────────────────────────────
# We use a fixed UTC-4 offset (EDT) for simplicity.
# Production: replace with zoneinfo.ZoneInfo("America/New_York")
ET_OFFSET = timezone(timedelta(hours=-4))

TICK_INTERVAL_SECONDS = 300  # 5 minutes
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
ORB_END_HOUR = 10
ORB_END_MINUTE = 0


def _now_et() -> datetime:
    return datetime.now(tz=ET_OFFSET)


def _alpaca_headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_PAPER_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_PAPER_SECRET_KEY", ""),
        "accept": "application/json",
        "content-type": "application/json",
    }


def _paper_base() -> str:
    return os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")


def _data_base() -> str:
    return "https://data.alpaca.markets"


class TradingJob:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    # ── Public interface ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the trading loop. Idempotent — no-op if already running."""
        async with state_lock:
            if self._task is not None and not self._task.done():
                return  # already running
            trading_state.status = "capturing_orb"
            trading_state.session_date = _now_et().date()
        self._task = asyncio.create_task(self._loop())
        logger.info("TradingJob started")

    async def stop(self) -> None:
        """Stop the trading loop gracefully."""
        import contextlib

        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        async with state_lock:
            trading_state.status = "stopped"
        logger.info("TradingJob stopped")

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        try:
            while True:
                now = _now_et()
                # Stop loop after market close
                if now.hour >= MARKET_CLOSE_HOUR:
                    async with state_lock:
                        trading_state.status = "closed"
                    break

                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    msg = f"tick error: {exc}"
                    logger.exception(msg)
                    async with state_lock:
                        log_error(msg)

                await asyncio.sleep(TICK_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            # Graceful shutdown — try to exit all open positions
            await self._close_all_positions("job_stopped")
            raise

    # ── Tick ──────────────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        now = _now_et()

        # Hard gate: outside trading hours
        after_open = now.hour > MARKET_OPEN_HOUR or (
            now.hour == MARKET_OPEN_HOUR and now.minute >= MARKET_OPEN_MINUTE
        )
        before_close = now.hour < MARKET_CLOSE_HOUR
        if not after_open or not before_close:
            return

        async with state_lock:
            trading_state.last_tick_at = datetime.utcnow()

        spy_price = await self._fetch_spy_price()

        # Phase 1: ORB capture window (9:30–10:00)
        orb_window_over = now.hour > ORB_END_HOUR or (
            now.hour == ORB_END_HOUR and now.minute >= ORB_END_MINUTE
        )

        if not orb_window_over:
            await self._update_orb()
            return

        # Phase 2+3: Trading + exit monitoring
        async with state_lock:
            if trading_state.status == "capturing_orb":
                trading_state.status = "trading"
            orb = trading_state.orb
            if orb is None:
                # Try to build ORB one more time
                pass

        if orb is None:
            await self._update_orb()
            async with state_lock:
                orb = trading_state.orb
            if orb is None:
                return

        # Exit monitoring
        await self._check_exits(now)

        # Entry signals
        for direction in ("CALL", "PUT"):
            await self._check_entry(direction, spy_price, orb, now)

    # ── ORB ───────────────────────────────────────────────────────────────────

    async def _update_orb(self) -> None:
        now = _now_et()
        session_start = now.replace(
            hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
        )
        bars = await self._fetch_spy_bars(session_start, now)
        orb = compute_orb(bars)
        if orb is not None:
            async with state_lock:
                trading_state.orb = orb
                log_event(
                    "orb_established",
                    reason=f"high={orb.high} low={orb.low} width={orb.width}",
                )

    # ── Entry ─────────────────────────────────────────────────────────────────

    async def _check_entry(
        self, direction: str, spy_price: float, orb: ORBLevels, now: datetime
    ) -> None:
        async with state_lock:
            # Update streak
            if (direction == "CALL" and spy_price > orb.high) or (
                direction == "PUT" and spy_price < orb.low
            ):
                trading_state.signal_streak[direction] = (
                    trading_state.signal_streak.get(direction, 0) + 1
                )
            else:
                trading_state.signal_streak[direction] = 0

            enter = should_enter(
                direction,
                spy_price,
                orb,
                trading_state.open_positions,
                trading_state.entry_counts,
                trading_state.signal_streak,
            )

        if enter:
            log_event("signal", direction=direction, price=spy_price)
            await self._place_entry(direction, spy_price, now)

    # ── Exit ──────────────────────────────────────────────────────────────────

    async def _check_exits(self, now: datetime) -> None:
        async with state_lock:
            positions_snapshot = list(trading_state.open_positions)

        for pos in positions_snapshot:
            mark = await self._fetch_option_mark(pos.contract_symbol)
            if mark is None:
                mark = pos.entry_premium  # fallback to entry price

            exit_flag, reason = should_exit(pos, mark, now)
            if exit_flag:
                await self._place_exit(pos, mark, reason)

    async def _close_all_positions(self, reason: str) -> None:
        async with state_lock:
            positions_snapshot = list(trading_state.open_positions)
        for pos in positions_snapshot:
            mark = await self._fetch_option_mark(pos.contract_symbol)
            await self._place_exit(pos, mark or pos.entry_premium, reason)

    # ── Order placement ───────────────────────────────────────────────────────

    async def _place_entry(self, direction: str, spy_price: float, now: datetime) -> None:
        try:
            # Determine expiry
            expiry = _next_option_expiry(now.date(), dte_preference=0)
            strike = select_strike(spy_price, direction)
            contract_symbol = format_contract_symbol(expiry, direction, strike)

            # Get ask price for sizing
            ask = await self._fetch_option_ask(contract_symbol)
            if ask is None or ask <= 0:
                log_error(f"No ask price for {contract_symbol}")
                return

            # Get portfolio value for sizing
            portfolio_value = await self._fetch_portfolio_value()
            if portfolio_value is None:
                log_error("Could not fetch portfolio value")
                return

            contracts = size_position(portfolio_value, ask)

            # Place order
            order_id = await self._place_order(
                symbol=contract_symbol,
                qty=contracts,
                side="buy",
            )
            if order_id is None:
                return

            async with state_lock:
                pos = OpenPosition(
                    contract_symbol=contract_symbol,
                    direction=direction,
                    contracts=contracts,
                    entry_premium=ask,
                    entry_order_id=order_id,
                    opened_at=datetime.utcnow(),
                )
                trading_state.open_positions.append(pos)
                trading_state.entry_counts[direction] = (
                    trading_state.entry_counts.get(direction, 0) + 1
                )
                trading_state.signal_streak[direction] = 0
                log_event(
                    "entry",
                    direction=direction,
                    contract_symbol=contract_symbol,
                    contracts=contracts,
                    price=ask,
                )

        except Exception as exc:
            log_error(f"entry error: {exc}")

    async def _place_exit(self, position: OpenPosition, mark: float, reason: str) -> None:
        try:
            order_id = await self._place_order(
                symbol=position.contract_symbol,
                qty=position.contracts,
                side="sell",
            )
            if order_id is None:
                return

            pnl = (mark - position.entry_premium) * position.contracts * 100

            async with state_lock:
                trading_state.open_positions = [
                    p
                    for p in trading_state.open_positions
                    if p.entry_order_id != position.entry_order_id
                ]
                trading_state.daily_pnl_cents += int(round(pnl * 100))
                log_event(
                    "exit",
                    direction=position.direction,
                    contract_symbol=position.contract_symbol,
                    contracts=position.contracts,
                    price=mark,
                    reason=reason,
                    pnl_usd=round(pnl, 2),
                )

        except Exception as exc:
            log_error(f"exit error: {exc}")

    async def _place_order(self, symbol: str, qty: int, side: str) -> str | None:
        """Place market order via Alpaca REST. Returns order_id or None on error."""
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_paper_base()}/v2/orders",
                    headers=_alpaca_headers(),
                    json=payload,
                )
            if resp.status_code in (200, 201):
                return str(resp.json().get("id") or "")
            log_error(f"order failed {resp.status_code}: {resp.text[:200]}")
            return None
        except Exception as exc:
            log_error(f"place_order exception: {exc}")
            return None

    # ── Data fetching ─────────────────────────────────────────────────────────

    async def _fetch_spy_price(self) -> float:
        """Fetch latest SPY trade price."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_data_base()}/v2/stocks/SPY/trades/latest",
                    headers=_alpaca_headers(),
                )
            if resp.status_code == 200:
                return float(resp.json()["trade"]["p"])
        except Exception as exc:
            log_error(f"fetch_spy_price: {exc}")
        return 0.0

    async def _fetch_spy_bars(self, start: datetime, end: datetime) -> list[dict]:
        """Fetch 1-min SPY bars between start and end."""
        try:
            params: dict[str, str] = {
                "timeframe": "1Min",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": "60",
                "feed": "iex",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_data_base()}/v2/stocks/SPY/bars",
                    headers=_alpaca_headers(),
                    params=params,
                )
            if resp.status_code == 200:
                raw = resp.json().get("bars", [])
                # Alpaca returns short keys: t, o, h, l, c, v — normalize to long form
                return [
                    {
                        "time": b.get("t", ""),
                        "open": b.get("o", b.get("open", 0)),
                        "high": b.get("h", b.get("high", 0)),
                        "low": b.get("l", b.get("low", 0)),
                        "close": b.get("c", b.get("close", 0)),
                        "volume": b.get("v", b.get("volume", 0)),
                    }
                    for b in raw
                ]
        except Exception as exc:
            log_error(f"fetch_spy_bars: {exc}")
        return []

    async def _fetch_option_mark(self, contract_symbol: str) -> float | None:
        """Fetch current mark (mid) price for an option contract."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_data_base()}/v1beta1/options/snapshots/{contract_symbol}",
                    headers=_alpaca_headers(),
                )
            if resp.status_code == 200:
                snap = resp.json()
                greeks = snap.get("greeks") or {}
                # Try mark price from snapshot
                quote = snap.get("latestQuote") or {}
                bid = float(quote.get("bp", 0) or 0)
                ask = float(quote.get("ap", 0) or 0)
                if bid > 0 and ask > 0:
                    return round((bid + ask) / 2, 4)
                _ = greeks  # unused in v1
        except Exception as exc:
            log_error(f"fetch_option_mark {contract_symbol}: {exc}")
        return None

    async def _fetch_option_ask(self, contract_symbol: str) -> float | None:
        """Fetch current ask price for an option contract."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_data_base()}/v1beta1/options/snapshots/{contract_symbol}",
                    headers=_alpaca_headers(),
                )
            if resp.status_code == 200:
                snap = resp.json()
                quote = snap.get("latestQuote") or {}
                ask = float(quote.get("ap", 0) or 0)
                if ask > 0:
                    return ask
        except Exception as exc:
            log_error(f"fetch_option_ask {contract_symbol}: {exc}")
        return None

    async def _fetch_portfolio_value(self) -> float | None:
        """Fetch paper account portfolio value."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_paper_base()}/v2/account",
                    headers=_alpaca_headers(),
                )
            if resp.status_code == 200:
                return float(resp.json().get("portfolio_value", 0))
        except Exception as exc:
            log_error(f"fetch_portfolio_value: {exc}")
        return None


# ── Singleton job instance ────────────────────────────────────────────────────

trading_job = TradingJob()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _next_option_expiry(today: date, dte_preference: int = 0) -> date:
    """Return nearest SPY option expiry date.

    SPY has options expiring Mon/Wed/Fri (and some Tue/Thu).
    For 0DTE: return today if it's a valid expiry day, else next valid day.
    For dte > 0: return today + dte_preference trading days.
    """
    # SPY daily options: every weekday has an expiry
    # For simplicity: use today if weekday, else next Monday
    target = today + timedelta(days=dte_preference)
    # Skip weekends
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target


def _build_status_response() -> dict:
    """Build the status response dict from current trading_state."""
    from app.trading.state import trading_state as ts

    return {
        "status": ts.status,
        "session_date": ts.session_date.isoformat() if ts.session_date else None,
        "orb_high": ts.orb.high if ts.orb else None,
        "orb_low": ts.orb.low if ts.orb else None,
        "open_positions": [
            {
                "contract_symbol": p.contract_symbol,
                "direction": p.direction,
                "contracts": p.contracts,
                "entry_premium": p.entry_premium,
                "current_mark": None,
                "unrealized_pnl_usd": None,
            }
            for p in ts.open_positions
        ],
        "entry_counts": ts.entry_counts,
        "daily_pnl_usd": round(ts.daily_pnl_cents / 100, 2),
        "last_tick_at": ts.last_tick_at.isoformat() + "Z" if ts.last_tick_at else None,
        "recent_errors": ts.errors,
    }
