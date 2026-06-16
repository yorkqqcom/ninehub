"""Tushare Pro collector with sliding-window rate limiting (tushare-quota.mdc)."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import date
from typing import Any, List, Optional

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.services.collectors.base import BaseCollector
from app.services.tushare.source_quota import points_to_max_calls_per_minute


_lock = threading.Lock()
_call_times: deque[float] = deque()


def max_calls_per_minute(limit_override: int | None = None) -> int:
    if limit_override is not None:
        return limit_override
    settings = get_settings()
    if settings.tushare_max_calls_per_minute is not None:
        return settings.tushare_max_calls_per_minute
    return points_to_max_calls_per_minute(settings.tushare_account_points)


def wait_before_pro_call(limit_override: int | None = None) -> None:
    """Sliding-window limiter shared by all TushareCollector instances."""
    limit = max_calls_per_minute(limit_override)
    with _lock:
        now = time.monotonic()
        while _call_times and _call_times[0] < now - 60:
            _call_times.popleft()
        if len(_call_times) >= limit:
            sleep_until = _call_times[0] + 60 - now
            if sleep_until > 0:
                time.sleep(sleep_until)
        _call_times.append(time.monotonic())


class TushareCollector(BaseCollector):
    source_type = "tushare"

    def __init__(
        self,
        token: Optional[str] = None,
        max_calls_per_minute: Optional[int] = None,
    ) -> None:
        self._token = token or get_settings().tushare_token
        self._max_calls_per_minute = max_calls_per_minute

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _call_pro(self, api_name: str, **params: Any) -> pd.DataFrame:
        wait_before_pro_call(self._max_calls_per_minute)
        if not self._token:
            raise ValueError("Tushare token not configured")
        import tushare as ts

        pro = ts.pro_api(self._token)
        df = getattr(pro, api_name)(**params)
        return df if df is not None else pd.DataFrame()

    def fetch_daily(
        self,
        stock_codes: List[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        start_s = start_date.strftime("%Y%m%d")
        end_s = end_date.strftime("%Y%m%d")
        for code in stock_codes:
            df = self._call_pro("daily", ts_code=code, start_date=start_s, end_date=end_s)
            if df is None or df.empty:
                continue
            df = df.rename(columns={"ts_code": "stock_code"})
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.date
            frames.append(
                df[["stock_code", "trade_date", "open", "high", "low", "close", "vol"]]
            )
        if not frames:
            return pd.DataFrame(
                columns=["stock_code", "trade_date", "open", "high", "low", "close", "vol"]
            )
        return pd.concat(frames, ignore_index=True)
