"""Generic fallback collect strategy (single probe call)."""

from __future__ import annotations

from app.sync.tia_collect.base import CollectStrategy, StrategyContext, StrategyResult
from app.sync.tia_collect.stock_codes import DEFAULT_STOCK_CODES


class GenericStrategy(CollectStrategy):
    def collect(self, ctx: StrategyContext) -> StrategyResult:
        self._estimate_calls(ctx, 1)
        probe_params = ctx.resolve_base_collect_params()

        if not probe_params:
            col_keys = {c.get("key") for c in ctx.schema.get("columns", [])}
            if "stock_code" in col_keys or "ts_code" in col_keys:
                probe_params = {"ts_code": DEFAULT_STOCK_CODES[0]}

        df = ctx.collector._call_pro(ctx.api_name, **probe_params)  # noqa: SLF001
        return self._upsert(ctx, df, api_calls=1)
