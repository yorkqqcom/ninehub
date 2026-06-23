"""Trade-date collect strategy."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.catalog.tia_probe_registry import last_trading_day
from app.services.trading_calendar.service import CN_HOLIDAYS
from app.sync.tia_collect.base import (
    CollectStrategy,
    StrategyContext,
    StrategyResult,
    concat_collect_frames,
)


def _trading_days_in_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in CN_HOLIDAYS:
            days.append(day)
        day += timedelta(days=1)
    if not days:
        days = [last_trading_day(end)]
    return days


def _trading_day_before(ref: date) -> date:
    cursor = ref - timedelta(days=1)
    while cursor.weekday() >= 5 or cursor in CN_HOLIDAYS:
        cursor -= timedelta(days=1)
    return cursor


TRADE_DATE_PAGE_SIZE = 5000


def _fetch_market_for_trade_date(
    ctx: StrategyContext,
    base_params: dict,
    trade_date_str: str,
) -> tuple[pd.DataFrame | None, int]:
    """Paginate Tushare trade_date queries (full market can exceed one page)."""
    drop_keys = ("ts_code", "start_date", "end_date", "period", "limit", "offset")
    frames: list[pd.DataFrame] = []
    api_calls = 0
    offset = 0
    while True:
        params = {k: v for k, v in base_params.items() if k not in drop_keys}
        params["trade_date"] = trade_date_str
        params["offset"] = offset
        params["limit"] = TRADE_DATE_PAGE_SIZE
        df = ctx.collector._call_pro(ctx.api_name, **params)  # noqa: SLF001
        api_calls += 1
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < TRADE_DATE_PAGE_SIZE:
            break
        offset += TRADE_DATE_PAGE_SIZE
    if not frames:
        return None, api_calls
    merged = concat_collect_frames(frames)
    return merged, api_calls


class TradeDateStrategy(CollectStrategy):
    def collect(self, ctx: StrategyContext) -> StrategyResult:
        trade_days = _trading_days_in_range(ctx.start_date, ctx.end_date)
        self._estimate_calls(ctx, len(trade_days))
        result = self._collect_trade_days(ctx, trade_days)

        if (
            ctx.sync_ctx.batch_mode == "daily"
            and result.rows_upserted == 0
            and trade_days
            and trade_days[-1] >= last_trading_day(date.today())
        ):
            prev = _trading_day_before(trade_days[-1])
            if prev not in trade_days:
                fallback = self._collect_trade_days(ctx, [prev])
                if fallback.rows_upserted > 0:
                    fallback.detail_json["trade_date_fallback"] = prev.isoformat()
                    return fallback
        return result

    def _collect_trade_days(
        self,
        ctx: StrategyContext,
        trade_days: list[date],
    ) -> StrategyResult:
        base_params = ctx.resolve_base_collect_params()
        drop_keys = ("ts_code", "start_date", "end_date", "period", "limit", "offset")

        frames: list[pd.DataFrame] = []
        api_calls = 0
        for td in trade_days:
            merged, calls = _fetch_market_for_trade_date(
                ctx, base_params, td.strftime("%Y%m%d")
            )
            api_calls += calls
            if merged is not None and not merged.empty:
                frames.append(merged)

        merged = concat_collect_frames(frames)
        result = self._upsert(ctx, merged, api_calls=api_calls)
        result.detail_json["trade_days"] = len(trade_days)
        return result
