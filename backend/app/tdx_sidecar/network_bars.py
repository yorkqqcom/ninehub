"""Optional pytdx network batch bars (fallback)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def fetch_network_bars_batch(
    *,
    stock_codes: list[str],
    period: str,
    start_date: date,
    end_date: date,
    connect_cfg_path: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch bars via pytdx HQ API; returns empty frame when pytdx unavailable."""
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        return pd.DataFrame(), {"source": "network", "error": "pytdx not installed"}

    category_map = {
        "1d": 9,
        "1w": 5,
        "1m": 8,
        "5m": 0,
    }
    category = category_map.get(period)
    if category is None:
        return pd.DataFrame(), {"source": "network", "error": f"unsupported period {period}"}

    api = TdxHq_API()
    connected = False
    try:
        if connect_cfg_path:
            from app.tdx_sidecar.pytdx_hosts import first_host_from_connect_cfg

            host, port = first_host_from_connect_cfg(connect_cfg_path)
            if host:
                connected = api.connect(host, port)
        if not connected:
            connected = api.connect("119.147.212.81", 7709)
        if not connected:
            return pd.DataFrame(), {"source": "network", "error": "connect failed"}

        frames: list[pd.DataFrame] = []
        for code in stock_codes:
            sym = code.strip().upper()
            if "." not in sym:
                continue
            digits, suffix = sym.split(".", 1)
            market = 1 if suffix in {"SH", "SS"} else 0
            bars = api.get_security_bars(category, market, digits, 0, 800)
            if not bars:
                continue
            df = api.to_df(bars)
            if df.empty:
                continue
            df["stock_code"] = sym
            if "datetime" in df.columns:
                df.rename(columns={"datetime": "trade_date"}, inplace=True)
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]
            if not df.empty:
                frames.append(df)
        if not frames:
            return pd.DataFrame(), {"source": "network", "api_calls": len(stock_codes)}
        merged = pd.concat(frames, ignore_index=True)
        return merged, {"source": "network", "api_calls": len(stock_codes), "rows": len(merged)}
    finally:
        try:
            api.disconnect()
        except Exception:
            pass
