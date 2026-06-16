"""Dynamic Tushare SyncHandler for TIA-activated APIs."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.services.collectors.tushare import TushareCollector
from app.services.tia.constants import data_type_aliases
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


class TushareApiHandler(SyncHandler):
    """Collect via Tushare pro API using sync_profile mode strategies."""

    def __init__(self, api_name: str, data_type: str, schema: dict[str, Any] | None = None) -> None:
        self.api_name = api_name
        self.data_type = data_type
        self.schema = schema or {}
        self._loader = TiaDataLoader()

    def collect(self, ctx: SyncContext) -> CollectResult:
        extra = ctx.extra or {}
        token = extra.get("token")
        if not token:
            raise ValidationError(
                "Tushare Token 未配置：请在「数据源」创建 Tushare 来源并填写 Token，"
                "或设置环境变量 TUSHARE_TOKEN"
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
            config = resolve_workflow_collect_config(schema, profile, batch_mode=batch_mode)
        else:
            profile = resolve_sync_profile(self.api_name, self.schema)
            config = resolve_collect_config(self.schema, profile)
        strategy = get_collect_strategy(profile.mode)

        try:
            collector = TushareCollector(
                token=token,
                max_calls_per_minute=extra.get("max_calls_per_minute"),
            )
            session: Optional[Session] = extra.get("session")
            st_ctx = StrategyContext(
                api_name=self.api_name,
                data_type=self.data_type,
                schema=self.schema,
                table_name=table_name,
                sync_ctx=ctx,
                collector=collector,
                loader=self._loader,
                profile=profile,
                config=config,
                session=session,
            )
            result = strategy.collect(st_ctx)
        except ValidationError:
            raise
        except ValueError as exc:
            return CollectResult(message=str(exc))
        except Exception as exc:
            return CollectResult(message=f"Tushare {self.api_name} failed: {exc}")

        return CollectResult(
            rows_upserted=result.rows_upserted,
            api_calls=result.api_calls,
            message=result.message,
            detail_json=result.detail_json,
        )


def register_tia_handler(
    api_name: str,
    data_type: str,
    schema: dict[str, Any] | None = None,
) -> None:
    handler = TushareApiHandler(api_name, data_type, schema)
    register_handler(data_type, handler)
    for alias in data_type_aliases(api_name):
        if alias != data_type:
            register_handler(alias, handler)
