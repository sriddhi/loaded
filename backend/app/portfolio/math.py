"""
Pure portfolio money math — no I/O.

Transactions are the source of truth; holdings are derived. Money is integer
cents end-to-end; share quantities are Decimal (fractional shares supported).
One rounding point per cents boundary (ROUND_HALF_EVEN).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, TypedDict


class Holding(TypedDict):
    symbol: str
    qty: Decimal
    avg_cost_cents: int
    cost_basis_cents: int
    realized_pnl_cents: int
    first_acquired: date | None


SHARE_TX_TYPES = ("buy", "sell")
CASH_TX_TYPES = ("dividend", "deposit", "withdrawal")
TX_TYPES = SHARE_TX_TYPES + CASH_TX_TYPES


def _to_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def derive_holdings(txs: list[dict[str, Any]]) -> dict[str, Holding]:
    """Replay ordered transactions into per-symbol holdings (average cost).

    txs must be ordered by (trade_date, id). Raises ValueError("oversell: ...")
    when a sell exceeds the held quantity at that point in the sequence.
    """
    holdings: dict[str, Holding] = {}
    for tx in txs:
        tx_type = tx["tx_type"]
        if tx_type not in SHARE_TX_TYPES:
            continue  # cash-only types never touch holdings
        symbol = str(tx["symbol"]).upper()
        qty = Decimal(str(tx["qty"]))
        price = int(tx["price_cents"])
        fees = int(tx.get("fees_cents") or 0)
        h = holdings.get(
            symbol,
            Holding(
                symbol=symbol,
                qty=Decimal("0"),
                avg_cost_cents=0,
                cost_basis_cents=0,
                realized_pnl_cents=0,
                first_acquired=None,
            ),
        )
        if tx_type == "buy":
            new_qty = h["qty"] + qty
            total_cost = h["qty"] * h["avg_cost_cents"] + qty * price + fees
            h["avg_cost_cents"] = _to_cents(total_cost / new_qty) if new_qty else 0
            h["qty"] = new_qty
            h["cost_basis_cents"] = _to_cents(new_qty * h["avg_cost_cents"])
            if h["first_acquired"] is None:
                h["first_acquired"] = tx["trade_date"]
        else:  # sell
            if qty > h["qty"]:
                raise ValueError(
                    f"oversell: selling {qty} {symbol} but only {h['qty']} held "
                    f"as of {tx['trade_date']}"
                )
            h["realized_pnl_cents"] += _to_cents(qty * (price - h["avg_cost_cents"])) - fees
            h["qty"] -= qty
            h["cost_basis_cents"] = _to_cents(h["qty"] * h["avg_cost_cents"])
            if h["qty"] == 0:
                h["avg_cost_cents"] = 0
                h["first_acquired"] = None
        holdings[symbol] = h
    return holdings


def cash_after(txs: list[dict[str, Any]], starting_cents: int = 0) -> int:
    """Cash balance after replaying amount_cents; raises on any negative prefix."""
    balance = starting_cents
    for tx in txs:
        balance += int(tx["amount_cents"])
        if balance < 0:
            raise ValueError(
                f"overdraw: cash would go to {balance / 100:.2f} on {tx['trade_date']}"
            )
    return balance


def validate_sequence(txs: list[dict[str, Any]]) -> tuple[dict[str, Holding], int]:
    """Validate a full ordered tx sequence; returns (holdings, cash_cents)."""
    holdings = derive_holdings(txs)
    cash = cash_after(txs)
    return holdings, cash


def amount_for(
    tx_type: str, qty: Decimal | None, price_cents: int | None, fees_cents: int, gross_cents: int
) -> int:
    """Signed cash effect of a transaction (buy negative, sell/income positive)."""
    if tx_type == "buy":
        assert qty is not None and price_cents is not None
        return -(_to_cents(qty * price_cents) + fees_cents)
    if tx_type == "sell":
        assert qty is not None and price_cents is not None
        return _to_cents(qty * price_cents) - fees_cents
    if tx_type in ("dividend", "deposit"):
        return abs(gross_cents)
    return -abs(gross_cents)  # withdrawal


def weights(values_cents: dict[str, int]) -> dict[str, float]:
    total = sum(values_cents.values())
    if total <= 0:
        return dict.fromkeys(values_cents, 0.0)
    return {s: v / total for s, v in values_cents.items()}


def concentration(values_cents: dict[str, int]) -> dict[str, Any]:
    """Top-1/top-5 weight and HHI with a plain-English label."""
    w = sorted(weights(values_cents).values(), reverse=True)
    hhi = sum(x * x for x in w)
    label = "diversified" if hhi < 0.10 else ("moderate" if hhi <= 0.18 else "concentrated")
    return {
        "top1_pct": round(w[0] * 100, 1) if w else 0.0,
        "top5_pct": round(sum(w[:5]) * 100, 1),
        "hhi": round(hhi, 4),
        "label": label if values_cents else "empty",
    }


def chained_twr(series: list[dict[str, Any]]) -> float | None:
    """Daily-chained time-weighted return over snapshot rows.

    Each row: {total_value_cents, net_flow_cents}; flows treated end-of-day:
    r_t = (V_t − F_t − V_{t−1}) / V_{t−1}. Returns cumulative TWR as a fraction,
    or None with fewer than 2 usable points.
    """
    if len(series) < 2:
        return None
    growth = 1.0
    for prev, cur in zip(series, series[1:], strict=False):
        v_prev = prev["total_value_cents"]
        if v_prev <= 0:
            continue
        r = (cur["total_value_cents"] - cur.get("net_flow_cents", 0) - v_prev) / v_prev
        growth *= 1.0 + r
    return growth - 1.0
