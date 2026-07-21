"""Watch domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuoteSnap:
    symbol: str
    last_price: float | None = None
    open: float | None = None
    pre_close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    change_pct: float | None = None
    ts_ms: int = 0
    degraded: bool = False
    stale: bool = False
    age_seconds: float = 0.0
    name: str = ""

    def usable_for_alert(self) -> bool:
        return (
            not self.stale
            and not self.degraded
            and self.last_price is not None
            and float(self.last_price) > 0
        )


@dataclass
class QuoteBatch:
    items: dict[str, QuoteSnap] = field(default_factory=dict)
    degraded: bool = False
    message: str = ""
    active_host: str = ""
    stale: bool = False


@dataclass
class AlertHit:
    rule_id: str
    symbol: str
    metric: str
    metric_value: float
    threshold: float
    message: str
    last_price: float
    rule_kind: str = "basic"
    rule_name: str = ""
    child_rule_ids: list[str] | None = None


def snap_from_dict(d: dict[str, Any], *, stale: bool = False, age: float = 0.0) -> QuoteSnap:
    return QuoteSnap(
        symbol=str(d.get("symbol") or ""),
        last_price=_f(d.get("last_price")),
        open=_f(d.get("open")),
        pre_close=_f(d.get("pre_close")),
        high=_f(d.get("high")),
        low=_f(d.get("low")),
        volume=_f(d.get("volume"), allow_zero=True),
        amount=_f(d.get("amount"), allow_zero=True),
        change_pct=_f(d.get("change_pct"), allow_zero=True),
        ts_ms=int(d.get("ts_ms") or 0),
        degraded=bool(d.get("degraded")),
        stale=stale,
        age_seconds=age,
        name=str(d.get("name") or ""),
    )


def _f(val: Any, *, allow_zero: bool = False) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if allow_zero:
        return f
    return f if f > 0 else None
