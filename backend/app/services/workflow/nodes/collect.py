"""Collect node — daily batch aware SyncExecutor delegation."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.catalog.registry import ensure_data_type_entry_sync, get_data_type_entry
from app.core.database import SyncSessionLocal
from app.core.exceptions import ValidationError
from app.models.workflow import WorkflowNode
from app.services.platform.service import PlatformService
from app.services.tia.constants import resolve_canonical_data_type
from app.services.tia.credentials import require_tushare_token
from app.services.tia.credentials_tdx import (
    build_sync_auth_extra,
    resolve_collect_source_credentials,
)
from app.services.tushare.quota import validate_points_for_data_type
from app.services.tushare.source_quota import resolve_max_calls_per_minute
from app.services.workflow.collect_batch import (
    extract_node_detail_json,
    resolve_batch_mode,
    resolve_run_batch_mode,
    resolve_workflow_collect_dates,
)
from app.services.workflow.nodes.base import NodeExecutionContext, NodeResult
from app.sync.executor import SyncExecutor
from app.sync.handlers import SyncContext, get_handler


class CollectNodeHandler:
    node_type = "collect"

    def execute(
        self,
        session: Session,
        node: WorkflowNode,
        *,
        skip_gates: bool = False,
        context: NodeExecutionContext | None = None,
    ) -> NodeResult:
        if not node.data_type:
            raise ValidationError(f"collect 节点 {node.node_id} 缺少 data_type")

        handler = get_handler(node.data_type)
        if handler is None:
            return NodeResult(
                status="success",
                message=f"采集完成（stub — {node.data_type} 无 Handler）",
            )

        creds = self._resolve_source(session, node.source_id, node.data_type)
        provider = str(creds.get("provider") or "tushare")
        source_config = dict(creds.get("source_config") or {})
        source_id = node.source_id or creds.get("source_id") or 1
        validate_points_for_data_type(
            node.data_type,
            provider=provider,
            source_config=source_config,
        )

        trigger_type = context.trigger_type if context else "manual"
        batch_mode = resolve_batch_mode(trigger_type, explicit=context.batch_mode if context else None)
        api_name = self._api_name(node.data_type)
        entry = ensure_data_type_entry_sync(session, node.data_type)
        schema = self._load_runtime_schema(session, node.data_type, api_name)

        from app.services.workflow.collect_batch import (
            resolve_workflow_collect_config,
            resolve_workflow_sync_profile,
        )

        profile = resolve_workflow_sync_profile(api_name, schema, batch_mode=batch_mode)
        start_str = PlatformService().resolve_sync_start_date_sync(session, node.data_type)
        if context is None:
            start_date = date.fromisoformat(start_str)
            end_date = date.today()
        else:
            start_date, end_date = resolve_workflow_collect_dates(
                session,
                workflow_id=context.workflow_id,
                node_id=context.node_id,
                mode=profile.mode,
                batch_mode=batch_mode,
                global_start_str=start_str,
                api_name=api_name,
            )

        if start_date > end_date and profile.mode != "snapshot":
            return NodeResult(
                status="success",
                message="日期范围为空，跳过采集",
                detail_json={
                    "batch_mode": batch_mode,
                    "collect_start_date": start_date.isoformat(),
                    "collect_end_date": end_date.isoformat(),
                },
            )

        stock_codes_table = entry.table_name
        if api_name == "stock_basic":
            stock_codes_table = entry.table_name

        rotation_offset = 0
        if context and batch_mode == "daily" and profile.mode in ("ts_code", "date_range", "period"):
            from app.services.workflow.collect_batch import get_last_successful_node_run

            last = get_last_successful_node_run(session, context.workflow_id, context.node_id)
            if last and last.result_json:
                rotation_offset = int(last.result_json.get("stock_code_offset") or 0)

        collect_session = SyncSessionLocal()
        try:
            result = SyncExecutor().run(
                SyncContext(
                    data_type=node.data_type,
                    source_id=source_id,
                    start_date=start_date,
                    end_date=end_date,
                    batch_mode=batch_mode,
                    extra=build_sync_auth_extra(
                        creds,
                        {
                            "session": collect_session,
                            "max_calls_per_minute": resolve_max_calls_per_minute(source_config),
                            "table_name": entry.table_name,
                            "stock_codes_table": stock_codes_table or "tushare_stock_basic",
                            "stock_code_offset": rotation_offset,
                            "workflow_schema": schema,
                            "workflow_profile": profile,
                        },
                    ),
                )
            )
            msg = (result.message or "").lower()
            if result.rows_upserted == 0 and any(
                token in msg for token in ("failed", "error", "not configured")
            ):
                collect_session.rollback()
            else:
                collect_session.commit()
        except Exception:
            collect_session.rollback()
            raise
        finally:
            collect_session.close()

        detail = extract_node_detail_json(
            result.detail_json,
            batch_mode=batch_mode,
            start_date=start_date,
            end_date=end_date,
        )

        if result.rows_upserted == 0 and result.api_calls == 0:
            msg = result.message or "采集无数据"
            if any(m in (msg or "").lower() for m in ("failed", "error", "not configured")):
                return NodeResult(status="failed", message=msg, detail_json=detail)
        return NodeResult(
            status="success",
            message=result.message or f"采集完成，写入 {result.rows_upserted} 行",
            detail_json=detail,
        )

    @staticmethod
    def _api_name(data_type: str) -> str:
        canonical = resolve_canonical_data_type(data_type)
        if canonical.startswith("tushare_"):
            return canonical[len("tushare_") :]
        if canonical.startswith("tdx_"):
            return canonical[len("tdx_") :]
        if canonical.startswith("tia_"):
            return canonical[len("tia_") :]
        return canonical

    @staticmethod
    def _load_runtime_schema(session: Session, data_type: str, api_name: str) -> dict:
        """Reload schema + handler from DB so upsert keys match current DDL."""
        from app.core.exceptions import NotFoundError
        from app.services.tia.override_service import TiaOverrideService

        try:
            override = TiaOverrideService().get_by_api_sync(session, api_name)
            TiaOverrideService().bootstrap_override(override)
            payload = override.override_json or {}
            schema = payload.get("schema") or payload
            return dict(schema) if isinstance(schema, dict) else {}
        except NotFoundError:
            handler = get_handler(data_type)
            return dict(getattr(handler, "schema") or {}) if handler else {}

    def _resolve_source(
        self,
        session: Session,
        source_id: int | None,
        data_type: str | None = None,
    ) -> dict[str, Any]:
        creds = resolve_collect_source_credentials(session, source_id, data_type=data_type)
        provider = str(creds.get("provider") or "tushare")
        if provider != "tdx":
            require_tushare_token(creds)
        return creds
