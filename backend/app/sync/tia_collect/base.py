"""TIA collect strategy base types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.services.collectors.tushare import TushareCollector
from app.services.tia.sync_profiles import SyncProfile
from app.services.tia.tia_data_loader import TiaDataLoader
from app.sync.handlers import CollectResult, SyncContext
from app.sync.tia_collect.config import CollectConfig


def concat_collect_frames(frames: list[pd.DataFrame]) -> pd.DataFrame | None:
    """Merge API response frames, skipping empty or all-NA chunks (pandas 2.x)."""
    valid = [frame for frame in frames if not frame.empty and not frame.isna().all().all()]
    if not valid:
        return None
    return pd.concat(valid, ignore_index=True)


@dataclass
class StrategyContext:
    api_name: str
    data_type: str
    schema: dict[str, Any]
    table_name: str
    sync_ctx: SyncContext
    collector: TushareCollector
    loader: TiaDataLoader
    profile: SyncProfile
    config: CollectConfig
    session: Session | None = None

    @property
    def start_date(self) -> date:
        return self.sync_ctx.start_date

    @property
    def end_date(self) -> date:
        return self.sync_ctx.end_date

    @property
    def extra(self) -> dict[str, Any]:
        return self.sync_ctx.extra or {}

    @property
    def collect_param_overrides(self) -> dict[str, Any]:
        return dict(self.extra.get("collect_params") or {})

    def resolve_base_collect_params(self) -> dict[str, Any]:
        from app.sync.tia_collect.params import (
            resolve_collect_params,
            strip_iteration_probe_filters,
        )

        params = resolve_collect_params(
            self.api_name,
            self.schema,
            **self.collect_param_overrides,
        )
        if self.profile.mode in ("ts_code", "date_range", "period"):
            params = strip_iteration_probe_filters(params, mode=self.profile.mode)
        elif self.profile.mode == "exchange_date_range" and self.api_name != "trade_cal":
            params = strip_iteration_probe_filters(params, mode=self.profile.mode)
        return params


@dataclass
class StrategyResult:
    rows_upserted: int = 0
    api_calls: int = 0
    message: str = ""
    detail_json: dict[str, Any] = field(default_factory=dict)


class CollectStrategy(ABC):
    @abstractmethod
    def collect(self, ctx: StrategyContext) -> StrategyResult:
        raise NotImplementedError

    def _upsert(
        self,
        ctx: StrategyContext,
        df: pd.DataFrame | None,
        *,
        api_calls: int,
    ) -> StrategyResult:
        if df is None or df.empty:
            return StrategyResult(
                api_calls=api_calls,
                message=f"TIA {ctx.api_name}: empty response",
                detail_json={
                    "mode": ctx.profile.mode,
                    "collect_start_date": ctx.start_date.isoformat(),
                    "collect_end_date": ctx.end_date.isoformat(),
                },
            )
        rows = 0
        df_rows = len(df)
        if ctx.session is not None:
            schema = dict(ctx.schema)
            schema.setdefault("api_name", ctx.api_name)
            rows = ctx.loader.upsert_dataframe(ctx.session, ctx.table_name, schema, df)
        message = f"TIA {ctx.api_name}: upserted {rows} rows"
        if df_rows > 0 and rows == 0:
            message = (
                f"TIA {ctx.api_name}: API 返回 {df_rows} 行但落库 0 行"
                "（检查 schema 列名是否与 API 字段一致，如 cal_date vs trade_date）"
            )
        return StrategyResult(
            rows_upserted=rows,
            api_calls=api_calls,
            message=message,
            detail_json={
                "mode": ctx.profile.mode,
                "collect_start_date": ctx.start_date.isoformat(),
                "collect_end_date": ctx.end_date.isoformat(),
                "api_calls": api_calls,
                "df_rows": df_rows,
            },
        )

    def _estimate_calls(self, ctx: StrategyContext, estimated: int) -> None:
        if estimated > ctx.config.max_api_calls_per_run:
            from app.core.exceptions import ValidationError

            raise ValidationError(
                f"Estimated {estimated} API calls exceeds limit "
                f"{ctx.config.max_api_calls_per_run} for {ctx.data_type}"
            )
