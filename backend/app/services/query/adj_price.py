"""Price adjustment helpers for OHLC indicators."""

from __future__ import annotations

from typing import Any


def apply_adjust(
    raw_value: Any,
    adjust: str | None,
    adj_factor: Any | None,
    latest_adj_factor: Any | None,
) -> float | None:
    if raw_value is None:
        return None
    try:
        price = float(raw_value)
    except (TypeError, ValueError):
        return None
    if not adjust or adjust == "none":
        return price
    try:
        af = float(adj_factor) if adj_factor is not None else None
    except (TypeError, ValueError):
        af = None
    if af is None:
        return price
    if adjust == "hfq":
        return price * af
    if adjust == "qfq":
        try:
            latest = float(latest_adj_factor) if latest_adj_factor is not None else af
        except (TypeError, ValueError):
            latest = af
        if latest == 0:
            return price
        return price * af / latest
    return price
