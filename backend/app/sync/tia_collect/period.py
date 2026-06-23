"""Financial period collect strategy."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.sync.tia_collect.base import (
    CollectStrategy,
    StrategyContext,
    StrategyResult,
    concat_collect_frames,
)
from app.sync.tia_collect.stock_codes import resolve_stock_codes

# APIs that return full market per report period via ``end_date`` (no ts_code loop).
PERIOD_MARKET_APIS: frozenset[str] = frozenset({"disclosure_date"})


def _period_param_name(api_name: str) -> str:
    return "end_date" if api_name in PERIOD_MARKET_APIS else "period"


def _periods_in_range(start: date, end: date) -> list[str]:
    """Full reporting periods across the year span (backfill)."""
    suffixes = ("0331", "0630", "0930", "1231")
    periods: list[str] = []
    for year in range(start.year, end.year + 1):
        for suffix in suffixes:
            periods.append(f"{year}{suffix}")
    return periods


def _recent_periods(end: date, count: int = 2) -> list[str]:
    suffixes = ("1231", "0930", "0630", "0331")
    periods: list[str] = []
    year = end.year
    while len(periods) < count and year >= end.year - 2:
        for suffix in suffixes:
            period_end = date(year, int(suffix[:2]), int(suffix[2:]))
            if period_end <= end:
                periods.append(f"{year}{suffix}")
                if len(periods) >= count:
                    return periods
        year -= 1
    return periods


class PeriodStrategy(CollectStrategy):
    def collect(self, ctx: StrategyContext) -> StrategyResult:
        if ctx.sync_ctx.batch_mode == "daily":
            periods = _recent_periods(ctx.end_date, count=2)
        else:
            periods = _periods_in_range(ctx.start_date, ctx.end_date)
        if not periods:
            periods = _recent_periods(ctx.end_date, count=1)

        base_params = ctx.resolve_base_collect_params()
        period_key = _period_param_name(ctx.api_name)
        frames: list[pd.DataFrame] = []
        api_calls = 0

        if ctx.api_name in PERIOD_MARKET_APIS:
            self._estimate_calls(ctx, len(periods))
            for period in periods:
                params = dict(base_params)
                params[period_key] = period
                df = ctx.collector._call_pro(ctx.api_name, **params)  # noqa: SLF001
                api_calls += 1
                if df is not None and not df.empty:
                    frames.append(df)
            merged = concat_collect_frames(frames)
            result = self._upsert(ctx, merged, api_calls=api_calls)
            result.detail_json["stock_codes_used"] = 0
            result.detail_json["periods"] = len(periods)
            result.detail_json["stock_code_offset"] = 0
            return result

        rotation_offset = int(ctx.extra.get("stock_code_offset") or 0)
        codes, next_offset = resolve_stock_codes(
            ctx.session,
            ctx.extra,
            max_codes=ctx.config.max_codes_per_run,
            rotation_offset=rotation_offset,
        )
        self._estimate_calls(ctx, len(codes) * len(periods))

        for code in codes:
            for period in periods:
                params = dict(base_params)
                params["ts_code"] = code
                params[period_key] = period
                df = ctx.collector._call_pro(ctx.api_name, **params)  # noqa: SLF001
                api_calls += 1
                if df is not None and not df.empty:
                    frames.append(df)

        merged = concat_collect_frames(frames)
        result = self._upsert(ctx, merged, api_calls=api_calls)
        result.detail_json["stock_codes_used"] = len(codes)
        result.detail_json["periods"] = len(periods)
        result.detail_json["stock_code_offset"] = next_offset
        return result
