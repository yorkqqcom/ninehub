"""Tushare Pro collector with sliding-window rate limiting (tushare-quota.mdc)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import date
from typing import Any, List, Optional

import pandas as pd
from tenacity import RetryCallState, retry, stop_after_attempt


def _tushare_retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome and retry_state.outcome.failed else None
    if exc is not None and _is_api_rate_limited(exc):
        return 61.0
    return min(8.0, 2 ** max(retry_state.attempt_number - 1, 0))

from app.core.config import get_settings
from app.services.collectors.base import BaseCollector
from app.services.tushare.source_quota import api_max_calls_per_minute, points_to_max_calls_per_minute


_lock = threading.Lock()
_call_times: deque[float] = deque()
_api_call_times: dict[str, deque[float]] = defaultdict(deque)


def max_calls_per_minute(limit_override: int | None = None) -> int:
    if limit_override is not None:
        return limit_override
    settings = get_settings()
    if settings.tushare_max_calls_per_minute is not None:
        return settings.tushare_max_calls_per_minute
    return points_to_max_calls_per_minute(settings.tushare_account_points)


def _drain_window(times: deque[float], limit: int) -> None:
    now = time.monotonic()
    while times and times[0] < now - 60:
        times.popleft()
    if len(times) >= limit:
        sleep_until = times[0] + 60.0 - now
        if sleep_until > 0:
            time.sleep(sleep_until)
        now = time.monotonic()
        while times and times[0] < now - 60:
            times.popleft()


def wait_before_pro_call(
    limit_override: int | None = None,
    *,
    api_name: str | None = None,
) -> None:
    """Sliding-window limiter: account tier cap plus optional per-interface cap."""
    account_limit = max_calls_per_minute(limit_override)
    api_limit = api_max_calls_per_minute(api_name) if api_name else None
    with _lock:
        _drain_window(_call_times, account_limit)
        if api_name and api_limit is not None:
            _drain_window(_api_call_times[api_name], api_limit)
        stamp = time.monotonic()
        _call_times.append(stamp)
        if api_name and api_limit is not None:
            _api_call_times[api_name].append(stamp)


def _is_api_rate_limited(exc: BaseException) -> bool:
    msg = str(exc)
    return "频率超限" in msg or "频次超限" in msg


class TushareCollector(BaseCollector):
    source_type = "tushare"

    def __init__(
        self,
        token: Optional[str] = None,
        max_calls_per_minute: Optional[int] = None,
    ) -> None:
        self._token = token or get_settings().tushare_token
        self._max_calls_per_minute = max_calls_per_minute

    @retry(stop=stop_after_attempt(5), wait=_tushare_retry_wait, reraise=True)
    def _call_pro(self, api_name: str, **params: Any) -> pd.DataFrame:
        wait_before_pro_call(self._max_calls_per_minute, api_name=api_name)
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
