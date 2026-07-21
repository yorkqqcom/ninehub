"""Built-in daily signals + metadata for the ops backtest form."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

SignalFn = Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]


def _as_float(params: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _as_int(params: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def signal_ma_golden_cross(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Entry when fast MA crosses above slow MA; exit on death cross."""
    fast = _as_int(params, "fast", 5)
    slow = _as_int(params, "slow", 20)
    if fast < 1 or slow < 2 or fast >= slow:
        fast, slow = 5, 20
    out = df.copy()
    out["ma_fast"] = out["close"].rolling(fast, min_periods=fast).mean()
    out["ma_slow"] = out["close"].rolling(slow, min_periods=slow).mean()
    above = (out["ma_fast"] > out["ma_slow"]).fillna(False).astype(bool)
    prev_above = above.shift(1).fillna(False).astype(bool)
    out["entry"] = above & ~prev_above
    out["exit"] = (~above) & prev_above
    return out


def signal_pct_change_threshold(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Entry when daily close return crosses threshold; exit next bar (one-day hold)."""
    threshold = _as_float(params, "threshold", 0.03)
    direction = str(params.get("direction") or "above").lower()
    out = df.copy()
    ret = out["close"].pct_change()
    if direction == "below":
        hit = ret <= -abs(threshold)
    else:
        hit = ret >= abs(threshold)
    hit = hit.fillna(False).astype(bool)
    out["entry"] = hit
    out["exit"] = hit.shift(1).fillna(False).astype(bool)
    return out


def signal_dual_ma_bull(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """State filter: close > short MA > long MA; enter on rising edge, exit when false."""
    short = _as_int(params, "ma_short", 10)
    long = _as_int(params, "ma_long", 30)
    if short < 1 or long < 2 or short >= long:
        short, long = 10, 30
    out = df.copy()
    out["ma_short"] = out["close"].rolling(short, min_periods=short).mean()
    out["ma_long"] = out["close"].rolling(long, min_periods=long).mean()
    state = (
        (out["close"] > out["ma_short"]) & (out["ma_short"] > out["ma_long"])
    ).fillna(False).astype(bool)
    prev = state.shift(1).fillna(False).astype(bool)
    out["entry"] = state & ~prev
    out["exit"] = (~state) & prev
    return out


SIGNAL_REGISTRY: dict[str, dict[str, Any]] = {
    "ma_golden_cross": {
        "id": "ma_golden_cross",
        "name": "MA 金叉",
        "description": "短期均线上穿长期均线时开仓，死叉平仓",
        "params": [
            {"key": "fast", "label": "快线周期", "type": "int", "default": 5, "min": 1, "max": 60},
            {"key": "slow", "label": "慢线周期", "type": "int", "default": 20, "min": 2, "max": 120},
        ],
        "fn": signal_ma_golden_cross,
    },
    "pct_change_threshold": {
        "id": "pct_change_threshold",
        "name": "收盘涨跌幅阈值",
        "description": "单日涨跌幅触及阈值时开仓，次日平仓",
        "params": [
            {
                "key": "threshold",
                "label": "阈值（小数，如 0.03=3%）",
                "type": "float",
                "default": 0.03,
                "min": 0.001,
                "max": 0.2,
            },
            {
                "key": "direction",
                "label": "方向",
                "type": "enum",
                "default": "above",
                "options": ["above", "below"],
            },
        ],
        "fn": signal_pct_change_threshold,
    },
    "dual_ma_bull": {
        "id": "dual_ma_bull",
        "name": "双均线多头",
        "description": "收盘价站上双均线且短均线在上时持有（状态过滤）",
        "params": [
            {"key": "ma_short", "label": "短均线", "type": "int", "default": 10, "min": 1, "max": 60},
            {"key": "ma_long", "label": "长均线", "type": "int", "default": 30, "min": 2, "max": 120},
        ],
        "fn": signal_dual_ma_bull,
    },
}


def list_signal_defs() -> list[dict[str, Any]]:
    return [
        {
            "id": meta["id"],
            "name": meta["name"],
            "description": meta["description"],
            "params": meta["params"],
        }
        for meta in SIGNAL_REGISTRY.values()
    ]


def get_signal_fn(signal_id: str) -> SignalFn:
    meta = SIGNAL_REGISTRY.get(signal_id)
    if meta is None:
        raise KeyError(signal_id)
    return meta["fn"]  # type: ignore[return-value]


def normalize_signal_params(signal_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Clamp / coerce params to the signal schema; drop unknown keys."""
    meta = SIGNAL_REGISTRY.get(signal_id)
    if meta is None:
        raise KeyError(signal_id)
    raw = dict(params or {})
    out: dict[str, Any] = {}
    for pdef in meta["params"]:
        key = str(pdef["key"])
        ptype = str(pdef.get("type") or "str")
        default = pdef.get("default")
        value = raw.get(key, default)
        if ptype == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = int(default) if default is not None else 0
            if pdef.get("min") is not None:
                value = max(int(pdef["min"]), value)
            if pdef.get("max") is not None:
                value = min(int(pdef["max"]), value)
        elif ptype == "float":
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = float(default) if default is not None else 0.0
            if pdef.get("min") is not None:
                value = max(float(pdef["min"]), value)
            if pdef.get("max") is not None:
                value = min(float(pdef["max"]), value)
        elif ptype == "enum":
            options = list(pdef.get("options") or [])
            value = str(value if value is not None else default or "")
            if options and value not in options:
                value = str(default if default in options else options[0])
        else:
            value = default if value is None else value
        out[key] = value
    # Keep MA pairs ordered; otherwise signal fn silently resets to defaults.
    if signal_id == "ma_golden_cross" and out.get("fast", 0) >= out.get("slow", 0):
        out["fast"], out["slow"] = 5, 20
    elif signal_id == "dual_ma_bull" and out.get("ma_short", 0) >= out.get("ma_long", 0):
        out["ma_short"], out["ma_long"] = 10, 30
    return out
