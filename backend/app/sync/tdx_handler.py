"""Dynamic TDX SyncHandler for TIA-activated APIs."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.services.tia.sync_profiles import resolve_sync_profile
from app.services.workflow.collect_batch import (
    resolve_workflow_collect_config,
    resolve_workflow_sync_profile,
)
from app.services.tia.tia_data_loader import TiaDataLoader
from app.sync.handlers import CollectResult, SyncContext, SyncHandler, register_handler
from app.sync.tia_collect.base import StrategyContext
from app.sync.tia_collect.config import resolve_collect_config
from app.sync.tia_collect.router import get_collect_strategy
from app.sync.tia_collect.tdx_strategies import (
    TdxConceptSnapshotStrategy,
    TdxNetworkBarStrategy,
    TdxVipdocImportStrategy,
)

_TDX_STRATEGIES = {
    "file_import": TdxVipdocImportStrategy(),
    "tdx_network": TdxNetworkBarStrategy(),
    "tdx_concept_snapshot": TdxConceptSnapshotStrategy(),
}


class TdxApiHandler(SyncHandler):
    """Collect via TDX Sidecar (vipdoc file import + network fallback)."""

    def __init__(self, api_name: str, data_type: str, schema: dict[str, Any] | None = None) -> None:
        self.api_name = api_name
        self.data_type = data_type
        self.schema = schema or {}
        self._loader = TiaDataLoader()

    def _resolve_strategy(self, mode: str):
        if mode in _TDX_STRATEGIES:
            return _TDX_STRATEGIES[mode]
        return get_collect_strategy(mode)

    def collect(self, ctx: SyncContext) -> CollectResult:
        extra = ctx.extra or {}
        base_url = extra.get("tdx_base_url") or (extra.get("source_config") or {}).get("base_url")
        if not base_url:
            raise ValidationError(
                "TDX Sidecar 未配置：请在「数据源」创建 TDX 来源并填写 base_url"
            )

        table_name = extra.get("table_name")
        if not table_name:
            raise ValidationError(f"No table_name for {self.data_type}")

        batch_mode = ctx.batch_mode if ctx.batch_mode in ("daily", "backfill") else "default"
        if batch_mode in ("daily", "backfill"):
            profile = extra.get("workflow_profile") or resolve_workflow_sync_profile(
                self.api_name, self.schema, batch_mode=batch_mode
            )
            schema = extra.get("workflow_schema") or self.schema
            config = resolve_workflow_collect_config(
                schema, profile, batch_mode=batch_mode, api_name=self.api_name
            )
        else:
            profile = resolve_sync_profile(self.api_name, self.schema)
            schema = self.schema
            config = resolve_collect_config(self.schema, profile)

        mode = profile.mode
        if self.api_name in ("concept_index", "concept_member"):
            mode = "tdx_concept_snapshot"
        elif mode not in _TDX_STRATEGIES and self.api_name.startswith("bar_"):
            mode = "file_import"

        strategy = self._resolve_strategy(mode)
        session: Optional[Session] = extra.get("session")
        st_ctx = StrategyContext(
            api_name=self.api_name,
            data_type=self.data_type,
            schema=schema,
            table_name=table_name,
            sync_ctx=ctx,
            collector=None,  # type: ignore[arg-type]
            loader=self._loader,
            profile=profile,
            config=config,
            session=session,
        )
        try:
            result = strategy.collect(st_ctx)
        except ValidationError:
            raise
        except Exception as exc:
            return CollectResult(message=f"TDX {self.api_name} failed: {exc}")

        return CollectResult(
            rows_upserted=result.rows_upserted,
            api_calls=result.api_calls,
            message=result.message,
            detail_json=result.detail_json,
        )


def register_tdx_handler(
    api_name: str,
    data_type: str,
    schema: dict[str, Any] | None = None,
) -> None:
    handler = TdxApiHandler(api_name, data_type, schema)
    register_handler(data_type, handler)
