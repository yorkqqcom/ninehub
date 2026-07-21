"""Cooldown cooldown state for watch alerts."""

from __future__ import annotations

import time
from typing import Any


def cooldown_active(
    state: dict[str, Any],
    *,
    rule_id: str,
    symbol: str,
    cooldown_seconds: int,
    cooldown_mode: str,
    trade_date: str,
) -> bool:
    key = f"{rule_id}:{symbol}"
    entries = state.get("entries") if isinstance(state.get("entries"), dict) else {}
    entry = entries.get(key) if isinstance(entries, dict) else None
    if not isinstance(entry, dict):
        return False
    mode = str(cooldown_mode or "interval").lower()
    if mode == "session":
        return str(entry.get("trade_date") or "") == trade_date
    last_ts = float(entry.get("ts") or 0)
    return (time.time() - last_ts) < max(0, int(cooldown_seconds or 0))


def mark_cooldown(
    state: dict[str, Any],
    *,
    rule_id: str,
    symbol: str,
    trade_date: str,
) -> dict[str, Any]:
    out = dict(state or {})
    entries = dict(out.get("entries") or {})
    entries[f"{rule_id}:{symbol}"] = {"ts": time.time(), "trade_date": trade_date}
    out["entries"] = entries
    out["trade_date"] = trade_date
    return out


def clear_cooldown_state() -> dict[str, Any]:
    return {"entries": {}}
