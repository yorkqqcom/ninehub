"""Snapshot (list_basic) collect strategy."""

from __future__ import annotations

import pandas as pd

from app.sync.tia_collect.base import CollectStrategy, StrategyContext, StrategyResult


class SnapshotStrategy(CollectStrategy):
    def collect(self, ctx: StrategyContext) -> StrategyResult:
        self._estimate_calls(ctx, 1)
        probe_params = ctx.resolve_base_collect_params()

        df = ctx.collector._call_pro(ctx.api_name, **probe_params)  # noqa: SLF001
        result = self._upsert(ctx, df, api_calls=1)
        result.detail_json["stock_codes_used"] = 0
        result.detail_json["collect_params"] = probe_params
        return result
