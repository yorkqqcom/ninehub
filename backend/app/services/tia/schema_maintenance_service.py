"""Schema maintenance — plan/apply for column alignment and unique-key sync."""

from __future__ import annotations

import copy
from typing import Any, Literal

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.models.sync_task import SyncTask
from app.services.catalog.canonical_standard import (
    resolve_schema_for_ddl,
    validate_canonical_for_ddl,
)
from app.services.tia.activation_service import TiaActivationService
from app.services.tia.collect_pattern import enrich_schema_collect, validate_collect_pattern
from app.services.tia.migration_service import TiaMigrationService
from app.services.tia.override_service import TiaOverrideService
from app.services.tia.schema_inference import (
    schema_to_catalog_columns,
    schema_to_catalog_filters,
)
from app.services.tia.sync_profiles import resolve_sync_profile
from app.services.tia.unique_key_registry import (
    build_registry_hint,
    build_schema_indexes,
    enrich_schema_keys,
    is_registry_registered,
)
from app.sync.tia_handler import register_tia_handler

SchemaMode = Literal["columns", "unique_keys"]


def _col_keys(schema: dict[str, Any]) -> set[str]:
    return {c["key"] for c in schema.get("columns", [])}


def _mapping_changes(current: dict[str, Any], target: dict[str, Any]) -> list[dict[str, str | None]]:
    cm = current.get("field_mappings") or {}
    tm = target.get("field_mappings") or {}
    changes: list[dict[str, str | None]] = []
    for api_field in sorted(set(cm) | set(tm)):
        before = cm.get(api_field)
        after = tm.get(api_field)
        if before != after:
            changes.append({"api_field": api_field, "before": before, "after": after})
    return changes


def _collect_mode(schema: dict[str, Any]) -> str | None:
    collect = schema.get("collect") or {}
    return collect.get("mode") or (schema.get("collect_pattern") or {}).get("mode")


def _apply_unique_keys_only(schema: dict[str, Any], unique_keys: list[str], table_name: str) -> dict[str, Any]:
    merged = copy.deepcopy(schema)
    merged["unique_keys"] = list(unique_keys)
    for col in merged.get("columns", []):
        col["nullable"] = col["key"] not in unique_keys
    indexes = build_schema_indexes(merged, table_name)
    merged["indexes"] = indexes
    uq = next((i for i in indexes if i.get("purpose") == "upsert"), None)
    if uq:
        merged["unique_constraint"] = {"name": uq["name"], "columns": uq["columns"]}
    elif "unique_constraint" in merged:
        del merged["unique_constraint"]
    return merged


def _table_row_count(session: Session, table_name: str) -> int:
    bind = session.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return 0
    try:
        return int(session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0)
    except Exception:
        return 0


class TiaSchemaMaintenanceService:
    def __init__(self) -> None:
        self._overrides = TiaOverrideService()
        self._migration = TiaMigrationService()

    def _load_activated_override(self, session: Session, api_name: str):
        override = self._overrides.get_by_api_sync(session, api_name)
        if not override.is_activated:
            raise ValidationError(f"Override for {api_name} is not activated; run L3 first")
        return override

    def _build_target_schema(
        self,
        session: Session,
        api_name: str,
        override,
    ) -> tuple[dict[str, Any], Any]:
        existing = (override.override_json or {}).get("schema") or {}
        table_name = override.table_name or f"tia_{api_name}"
        schema = resolve_schema_for_ddl(api_name, existing, force_rebuild=True)
        pattern_validation = validate_collect_pattern(api_name)
        schema = enrich_schema_collect(schema, api_name)
        schema = enrich_schema_keys(schema, api_name, table_name=table_name)
        return schema, pattern_validation

    def _merge_for_modes(
        self,
        current: dict[str, Any],
        target: dict[str, Any],
        modes: list[SchemaMode],
        *,
        api_name: str,
        table_name: str,
    ) -> dict[str, Any]:
        mode_set = set(modes)
        if "columns" in mode_set and "unique_keys" in mode_set:
            return copy.deepcopy(target)
        if "columns" in mode_set:
            merged = copy.deepcopy(target)
            preserved_keys = list(current.get("unique_keys") or target.get("unique_keys") or [])
            return _apply_unique_keys_only(merged, preserved_keys, table_name)
        if "unique_keys" in mode_set:
            registry_keys = list(target.get("unique_keys") or [])
            return _apply_unique_keys_only(current, registry_keys, table_name)
        return copy.deepcopy(current)

    def _compute_diff(
        self,
        session: Session,
        current: dict[str, Any],
        target: dict[str, Any],
        *,
        api_name: str,
        table_name: str,
        pattern_validation,
    ) -> dict[str, Any]:
        current_cols = _col_keys(current)
        target_cols = _col_keys(target)
        current_keys = list(current.get("unique_keys") or [])
        registry_keys = list(target.get("unique_keys") or [])

        columns_added = sorted(target_cols - current_cols)
        columns_dropped = sorted(current_cols - target_cols)
        mapping_changes = _mapping_changes(current, target)
        collect_before = _collect_mode(current)
        collect_after = _collect_mode(target)
        collect_changed = collect_before != collect_after
        unique_keys_changed = current_keys != registry_keys

        columns_drift = bool(
            columns_added or columns_dropped or mapping_changes or collect_changed
        )
        keys_drift = unique_keys_changed
        registry_registered = is_registry_registered(api_name)
        row_count = _table_row_count(session, table_name)

        ddl_errors = validate_canonical_for_ddl(target, api_name)
        warnings: list[str] = []
        if pattern_validation.blocking_errors:
            warnings.extend(pattern_validation.blocking_errors)
        if columns_dropped:
            warnings.append(f"将删除列: {', '.join(columns_dropped)}")
        if unique_keys_changed and row_count > 0:
            warnings.append(
                f"表 {table_name} 已有 {row_count} 行，唯一键变更可能导致 upsert 冲突，建议清表或手工迁移"
            )
        if keys_drift and not registry_registered:
            warnings.append(
                f"API '{api_name}' 未在 unique_key_registry.py 登记，须先改代码再同步唯一键"
            )

        available_modes: list[str] = []
        if columns_drift:
            available_modes.append("columns")
        if keys_drift and registry_registered:
            available_modes.append("unique_keys")

        needs_confirm_risk = bool(columns_dropped or (unique_keys_changed and row_count > 0))

        return {
            "columns_before": sorted(current_cols),
            "columns_after": sorted(target_cols),
            "columns_added": columns_added,
            "columns_dropped": columns_dropped,
            "mapping_changes": mapping_changes,
            "collect_mode_before": collect_before,
            "collect_mode_after": collect_after,
            "unique_keys_before": current_keys,
            "unique_keys_registry": registry_keys,
            "unique_keys_changed": unique_keys_changed,
            "columns_drift": columns_drift,
            "keys_drift": keys_drift,
            "registry_registered": registry_registered,
            "registry_hint": build_registry_hint(api_name, target.get("api_fields")),
            "row_count": row_count,
            "ddl_errors": ddl_errors,
            "warnings": warnings,
            "available_modes": available_modes,
            "needs_confirm_risk": needs_confirm_risk,
            "has_drift": columns_drift or keys_drift,
        }

    def plan(self, session: Session, api_name: str) -> dict[str, Any]:
        override = self._load_activated_override(session, api_name)
        current = (override.override_json or {}).get("schema") or {}
        table_name = override.table_name or f"tia_{api_name}"
        target, pattern_validation = self._build_target_schema(session, api_name, override)

        diff = self._compute_diff(
            session,
            current,
            target,
            api_name=api_name,
            table_name=table_name,
            pattern_validation=pattern_validation,
        )

        return {
            "api_name": api_name,
            "data_type": override.data_type,
            "table_name": table_name,
            **diff,
        }

    def apply(
        self,
        session: Session,
        api_name: str,
        modes: list[SchemaMode],
        *,
        confirm_risk: bool = False,
    ) -> dict[str, Any]:
        if not modes:
            raise ValidationError("At least one maintenance mode is required")

        override = self._load_activated_override(session, api_name)
        current = (override.override_json or {}).get("schema") or {}
        table_name = override.table_name or f"tia_{api_name}"
        target, pattern_validation = self._build_target_schema(session, api_name, override)

        diff = self._compute_diff(
            session,
            current,
            target,
            api_name=api_name,
            table_name=table_name,
            pattern_validation=pattern_validation,
        )

        mode_set = set(modes)
        if "unique_keys" in mode_set and not is_registry_registered(api_name):
            hint = build_registry_hint(api_name, target.get("api_fields"))
            raise ValidationError(
                "唯一键未在 registry 登记: "
                f"请在 {hint['registry_file']} 添加 {hint['registry_snippet']}"
            )

        if "columns" in mode_set and pattern_validation.blocking_errors:
            raise ValidationError(
                "采集模式校验未通过: " + "; ".join(pattern_validation.blocking_errors)
            )

        if diff["needs_confirm_risk"] and not confirm_risk:
            raise ValidationError(
                "存在删列或唯一键变更风险，须设置 confirm_risk=true 后再应用"
            )

        merged = self._merge_for_modes(
            current,
            target,
            list(mode_set),
            api_name=api_name,
            table_name=table_name,
        )

        if "columns" in mode_set:
            ddl_errors = validate_canonical_for_ddl(merged, api_name)
            if ddl_errors:
                raise ValidationError(f"Schema not DDL-ready: {'; '.join(ddl_errors)}")

        old_col_keys = _col_keys(current)
        old_unique = list(current.get("unique_keys") or [])

        sync_columns = "columns" in mode_set
        sync_unique = "unique_keys" in mode_set
        if sync_columns or sync_unique:
            self._migration.ensure_table(session, table_name, merged)
            ddl_sync = self._migration.sync_table_schema(
                session,
                table_name,
                merged,
                old_schema=current if sync_unique else None,
                confirm_risk=confirm_risk,
                sync_columns=sync_columns,
                sync_unique=sync_unique,
            )
        else:
            ddl_sync = {
                "columns_added": [],
                "columns_dropped": [],
                "unique_index_created": False,
                "browse_indexes_created": [],
            }

        override = self._overrides.get_by_api_sync(session, api_name)
        oj = dict(override.override_json or {})
        oj["schema"] = copy.deepcopy(merged)
        override.override_json = oj
        flag_modified(override, "override_json")
        session.flush()

        self._overrides.apply_to_registry(
            override,
            columns=schema_to_catalog_columns(merged),
            filters=schema_to_catalog_filters(merged),
        )
        register_tia_handler(api_name, override.data_type, merged)

        profile = resolve_sync_profile(api_name, merged)
        task = session.execute(
            select(SyncTask).where(SyncTask.data_type == override.data_type)
        ).scalar_one_or_none()
        task_updated = False
        if task is not None and ("columns" in mode_set or "unique_keys" in mode_set):
            TiaActivationService._apply_sync_profile(
                task,
                profile,
                force_update_cron="columns" in mode_set,
            )
            task_updated = True

        session.flush()
        new_col_keys = _col_keys(merged)
        return {
            "api_name": api_name,
            "data_type": override.data_type,
            "table_name": table_name,
            "modes_applied": sorted(mode_set),
            "columns_before": sorted(old_col_keys),
            "columns_after": sorted(new_col_keys),
            "unique_keys_before": old_unique,
            "unique_keys_after": merged.get("unique_keys") or [],
            "collect_mode": _collect_mode(merged),
            "columns_added": ddl_sync.get("columns_added") or [],
            "columns_dropped": ddl_sync.get("columns_dropped") or [],
            "unique_index_created": bool(ddl_sync.get("unique_index_created")),
            "browse_indexes_created": ddl_sync.get("browse_indexes_created") or [],
            "indexes": merged.get("indexes") or [],
            "unique_constraint": merged.get("unique_constraint"),
            "sync_task_updated": task_updated,
            "schedule_cron": task.schedule_cron if task else None,
            "message": "Schema maintenance applied",
        }

    def registry_hint(self, api_name: str) -> dict[str, Any]:
        from app.services.catalog.canonical_standard import resolve_api_fields

        fields = resolve_api_fields(api_name)
        return build_registry_hint(api_name, fields)
