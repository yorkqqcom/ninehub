"""Optional pytdx network batch bars (fallback)."""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import pandas as pd

from app.tdx_sidecar.paths import merge_paths_config, resolve_effective_paths
from app.tdx_sidecar.pytdx_gate import pytdx_slot
from app.tdx_sidecar.pytdx_hosts import host_list

logger = logging.getLogger(__name__)

_MAX_HOSTS = 4
_CONNECT_TIMEOUT = 2
_INDEX_RE = re.compile(r"^880\d{3}$")
# pytdx: 7=1min (common), 8=1min alt, 9=daily, 0=5min, 4=daily alt
_PERIOD_CATEGORIES: dict[str, list[int]] = {
    "1m": [7, 8],
    "5m": [0],
    "1d": [9, 4],
    "1w": [5],
}


def _normalize_index_code(raw: str) -> str | None:
    text = str(raw or "").strip().upper()
    if text.endswith(".TDX"):
        text = text[: -len(".TDX")]
    if _INDEX_RE.match(text):
        return text
    return None


def all_codes_are_concept_index(stock_codes: list[str]) -> bool:
    """True when every code is a TDX concept index 880xxx (skip vipdoc)."""
    if not stock_codes:
        return False
    for code in stock_codes:
        if _normalize_index_code(code) is None:
            return False
    return True


def _normalize_bar_frame(df: pd.DataFrame, *, period: str) -> pd.DataFrame:
    """Ensure trade_date (date) and optional bar_time for minute bars."""
    out = df.copy()
    if "datetime" in out.columns:
        ts = pd.to_datetime(out["datetime"], errors="coerce")
    elif {"year", "month", "day"}.issubset(out.columns):
        y = out["year"].astype(int)
        m = out["month"].astype(int)
        d = out["day"].astype(int)
        if period in {"1m", "5m"} and {"hour", "minute"}.issubset(out.columns):
            hh = out["hour"].astype(int)
            mm = out["minute"].astype(int)
            ts = pd.to_datetime(
                dict(year=y, month=m, day=d, hour=hh, minute=mm),
                errors="coerce",
            )
        else:
            ts = pd.to_datetime(dict(year=y, month=m, day=d), errors="coerce")
    elif "trade_date" in out.columns:
        ts = pd.to_datetime(out["trade_date"], errors="coerce")
    else:
        return pd.DataFrame()

    out["bar_time"] = ts
    out["trade_date"] = ts.dt.date
    out = out.dropna(subset=["trade_date"])
    # 清洗 pytdx 偶发浮点噪点（如 1e-39），避免污染成交量/均价
    for col in ("vol", "volume", "amount"):
        if col in out.columns:
            s = pd.to_numeric(out[col], errors="coerce")
            out[col] = s.where(s > 1e-6, 0.0)
    return out


def _filter_or_last_session(
    df: pd.DataFrame,
    *,
    period: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]
    if not filtered.empty:
        return filtered
    if period in {"1m", "5m"}:
        last_day = df["trade_date"].max()
        if last_day is not None:
            return df[df["trade_date"] == last_day]
    return filtered


def _fetch_one_symbol_bars(
    api: Any,
    *,
    sym: str,
    period: str,
    categories: list[int],
    start_date: date,
    end_date: date,
) -> tuple[pd.DataFrame, int | None]:
    """Return (frame, category_used) for one stock or 880 index."""
    index_code = _normalize_index_code(sym)
    if index_code:
        for cat in categories:
            for market in (1, 0):
                bars = api.get_index_bars(cat, market, index_code, 0, 800) or []
                if not bars:
                    continue
                raw = api.to_df(bars)
                if raw is None or raw.empty:
                    continue
                raw = _normalize_bar_frame(raw, period=period)
                if raw.empty:
                    continue
                raw["stock_code"] = index_code
                raw = _filter_or_last_session(
                    raw, period=period, start_date=start_date, end_date=end_date
                )
                if not raw.empty:
                    return raw, cat
        return pd.DataFrame(), None

    if "." not in sym:
        return pd.DataFrame(), None
    digits, suffix = sym.split(".", 1)
    market = 1 if suffix in {"SH", "SS"} else 0
    for cat in categories:
        bars = api.get_security_bars(cat, market, digits, 0, 800) or []
        if not bars:
            continue
        raw = api.to_df(bars)
        if raw is None or raw.empty:
            continue
        raw = _normalize_bar_frame(raw, period=period)
        if raw.empty:
            continue
        raw["stock_code"] = sym
        raw = _filter_or_last_session(
            raw, period=period, start_date=start_date, end_date=end_date
        )
        if not raw.empty:
            return raw, cat
    return pd.DataFrame(), None


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
        return pd.DataFrame(), {
            "source": "network",
            "error": "pytdx not installed",
            "degraded": True,
        }

    categories = _PERIOD_CATEGORIES.get(period)
    if not categories:
        return pd.DataFrame(), {
            "source": "network",
            "error": f"unsupported period {period}",
            "degraded": True,
        }

    if not connect_cfg_path:
        eff = resolve_effective_paths(merge_paths_config())
        connect_cfg_path = eff.connect_cfg_path

    hosts = host_list(connect_cfg_path)[:_MAX_HOSTS]
    api = TdxHq_API(raise_exception=False)
    last_error = "connect failed"
    category_used: int | None = None
    active_host = ""

    with pytdx_slot(8.0) as got:
        if not got:
            return pd.DataFrame(), {
                "source": "network",
                "error": "pytdx busy",
                "degraded": True,
                "api_calls": 0,
            }
        try:
            for host, port in hosts:
                try:
                    if not api.connect(host, port, time_out=_CONNECT_TIMEOUT):
                        last_error = f"connect failed {host}:{port}"
                        continue
                    active_host = f"{host}:{port}"
                    frames: list[pd.DataFrame] = []
                    used_cat: int | None = None
                    for code in stock_codes:
                        sym = code.strip().upper()
                        df_sym, cat = _fetch_one_symbol_bars(
                            api,
                            sym=sym,
                            period=period,
                            categories=categories,
                            start_date=start_date,
                            end_date=end_date,
                        )
                        if not df_sym.empty:
                            frames.append(df_sym)
                            if cat is not None:
                                used_cat = cat
                    if frames:
                        category_used = used_cat
                        merged = pd.concat(frames, ignore_index=True)
                        meta: dict[str, Any] = {
                            "source": "network",
                            "api_calls": len(stock_codes),
                            "rows": len(merged),
                            "active_host": active_host,
                            "degraded": False,
                        }
                        if category_used is not None:
                            meta["category_used"] = category_used
                        return merged, meta
                    last_error = f"empty bars on {active_host}"
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    logger.debug("network bars host %s failed: %s", active_host or host, exc)
                finally:
                    try:
                        api.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
            return pd.DataFrame(), {
                "source": "network",
                "error": last_error,
                "degraded": True,
                "api_calls": len(stock_codes),
            }
        finally:
            try:
                api.disconnect()
            except Exception:  # noqa: BLE001
                pass
