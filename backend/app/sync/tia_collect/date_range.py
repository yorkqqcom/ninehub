"""Date-range collect strategy (ts_code + start_date + end_date)."""

from __future__ import annotations

import pandas as pd

from app.sync.tia_collect.base import (
    CollectStrategy,
    StrategyContext,
    StrategyResult,
    concat_collect_frames,
)
from app.sync.tia_collect.stock_codes import resolve_stock_codes


class DateRangeStrategy(CollectStrategy):
    def collect(self, ctx: StrategyContext) -> StrategyResult:
        rotation_offset = int(ctx.extra.get("stock_code_offset") or 0)
        codes, next_offset = resolve_stock_codes(
            ctx.session,
            ctx.extra,
            max_codes=ctx.config.max_codes_per_run,
            rotation_offset=rotation_offset,
        )
        self._estimate_calls(ctx, len(codes))

        base_params = ctx.resolve_base_collect_params()

        start_s = ctx.start_date.strftime("%Y%m%d")
        end_s = ctx.end_date.strftime("%Y%m%d")
        frames: list[pd.DataFrame] = []
        api_calls = 0

        for code in codes:
            params = dict(base_params)
            params.pop("trade_date", None)
            params["ts_code"] = code
            params["start_date"] = start_s
            params["end_date"] = end_s
            df = ctx.collector._call_pro(ctx.api_name, **params)  # noqa: SLF001
            api_calls += 1
            if df is not None and not df.empty:
                frames.append(df)

        merged = concat_collect_frames(frames)
        result = self._upsert(ctx, merged, api_calls=api_calls)
        result.detail_json["stock_codes_used"] = len(codes)
        result.detail_json["stock_code_offset"] = next_offset
        return result
