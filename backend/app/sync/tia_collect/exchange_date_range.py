"""Exchange + date-range collect strategy (trade_cal: one call per sync window)."""

from __future__ import annotations

from app.sync.tia_collect.base import CollectStrategy, StrategyContext, StrategyResult


class ExchangeDateRangeStrategy(CollectStrategy):
    """Single Tushare call with exchange/start_date/end_date from sync context."""

    def collect(self, ctx: StrategyContext) -> StrategyResult:
        self._estimate_calls(ctx, 1)

        params = ctx.resolve_base_collect_params()
        params = dict(params)
        params["start_date"] = ctx.start_date.strftime("%Y%m%d")
        params["end_date"] = ctx.end_date.strftime("%Y%m%d")

        df = ctx.collector._call_pro(ctx.api_name, **params)  # noqa: SLF001
        result = self._upsert(ctx, df, api_calls=1)
        result.detail_json["exchange_date_range"] = True
        result.detail_json["collect_params"] = params
        return result
