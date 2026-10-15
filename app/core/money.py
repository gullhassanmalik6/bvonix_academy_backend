"""Decimal amounts for fee math. Stored documents keep the existing numeric fields."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


_CENTS = Decimal("0.01")


def money(value) -> Decimal:
    """Two-decimal amount. Non-numeric values become zero."""
    try:
        amount = Decimal(str(value if value is not None else 0))
    except Exception:
        return Decimal("0.00")
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


def money_float(value) -> float:
    return float(money(value))
