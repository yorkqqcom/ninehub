"""Resolve and validate per-task Tushare collect input parameters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.sync_task import SyncTask
from app.models.tia_override import TiaOverride
from app.services.tia.collect_pattern import resolve_collect_pattern
from app.services.tia.constants import DEFAULT_PROVIDER, resolve_canonical_data_type
from app.services.tia.sync_profiles import resolve_sync_profile
from app.sync.tia_collect.params import resolve_collect_params, sanitize_collect_params

# Keys set by collect strategies at runtime — not editable on the task form.
MODE_RUNTIME_KEYS: dict[str, frozenset[str]] = {
    "snapshot": frozenset(),
    "generic": frozenset(),
    "exchange_date_range": frozenset({"start_date", "end_date"}),
    "date_range": frozenset({"ts_code", "start_date", "end_date"}),
    "trade_date": frozenset({"trade_date"}),
    "ts_code": frozenset({"ts_code"}),
    "period": frozenset({"ts_code", "period"}),
}

PROBE_ONLY_KEYS = frozenset({"fields", "limit"})

PARAM_HINTS: dict[str, str] = {
    "exchange": "交易所：SSE / SZSE / BSE；空字符串表示全部",
    "list_status": "上市状态：L 上市 / D 退市 / P 暂停",
    "hs_type": "沪深港通类型：SH / SZ",
    "is_hs": "是否沪深港通：N / H / S",
    "market": "市场类型",
    "start_date": "开始日期 YYYYMMDD（区间策略自动注入）",
    "end_date": "结束日期 YYYYMMDD（区间策略自动注入）",
    "trade_date": "交易日 YYYYMMDD（按日策略自动注入）",
    "ts_code": "证券代码（按代码迭代策略自动注入）",
    "period": "报告期 YYYYMMDD（财报策略自动注入）",
}


def _api_name_from_data_type(data_type: str) -> str | None:
    canonical = resolve_canonical_data_type(data_type)
    prefix = f"{DEFAULT_PROVIDER}_"
    if canonical.startswith(prefix):
        return canonical[len(prefix) :]
    legacy = "tia_"
    if canonical.startswith(legacy):
        return canonical[len(legacy) :]
    return None


def _schema_for_data_type_sync(session: Session, data_type: str) -> tuple[str | None, dict[str, Any]]:
    override = session.execute(
        select(TiaOverride).where(TiaOverride.data_type == data_type)
    ).scalar_one_or_none()
    if override is None:
        canonical = resolve_canonical_data_type(data_type)
        override = session.execute(
            select(TiaOverride).where(TiaOverride.data_type == canonical)
        ).scalar_one_or_none()
    if override is not None:
        schema = (override.override_json or {}).get("schema") or {}
        return override.api_name, schema
    api_name = _api_name_from_data_type(data_type)
    return api_name, {}


async def _schema_for_data_type_async(
    session: AsyncSession,
    data_type: str,
) -> tuple[str | None, dict[str, Any]]:
    override = (
        await session.execute(select(TiaOverride).where(TiaOverride.data_type == data_type))
    ).scalar_one_or_none()
    if override is None:
        canonical = resolve_canonical_data_type(data_type)
        override = (
            await session.execute(select(TiaOverride).where(TiaOverride.data_type == canonical))
        ).scalar_one_or_none()
    if override is not None:
        schema = (override.override_json or {}).get("schema") or {}
        return override.api_name, schema
    return _api_name_from_data_type(data_type), {}


def normalize_task_collect_params(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate and sanitize task-level collect param overrides."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValidationError("collect_params must be a JSON object")
    cleaned = sanitize_collect_params(dict(raw))
    for key in cleaned:
        if key in PROBE_ONLY_KEYS:
            raise ValidationError(f"collect_params must not include probe-only key '{key}'")
        val = cleaned[key]
        if val is not None and not isinstance(val, (str, int, float, bool)):
            raise ValidationError(f"collect_params['{key}'] must be scalar")
        if isinstance(val, str) and len(val) > 256:
            raise ValidationError(f"collect_params['{key}'] too long (max 256)")
    if len(cleaned) > 32:
        raise ValidationError("collect_params supports at most 32 keys")
    return cleaned


def validate_task_collect_params_for_api(
    api_name: str | None,
    schema: dict[str, Any],
    raw: dict[str, Any] | None,
) -> dict[str, Any] | None:
    params = normalize_task_collect_params(raw)
    if not params or not api_name:
        return params
    profile = resolve_sync_profile(api_name, schema)
    runtime = MODE_RUNTIME_KEYS.get(profile.mode, frozenset())
    blocked = [k for k in params if k in runtime]
    if blocked:
        raise ValidationError(
            f"collect_params must not include runtime keys {blocked} "
            f"(mode={profile.mode} sets them automatically)"
        )
    return params


def build_collect_config(
    *,
    api_name: str | None,
    schema: dict[str, Any],
    task_overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    if not api_name:
        return {
            "api_name": None,
            "collect_mode": None,
            "default_params": {},
            "task_overrides": task_overrides or {},
            "effective_params": {},
            "runtime_keys": [],
            "editable_keys": [],
            "param_hints": {},
        }

    pattern = resolve_collect_pattern(api_name)
    profile = resolve_sync_profile(api_name, schema)
    runtime_keys = sorted(MODE_RUNTIME_KEYS.get(profile.mode, frozenset()))
    default_params = resolve_collect_params(api_name, schema)
    overrides = dict(task_overrides or {})
    for key in runtime_keys:
        overrides.pop(key, None)
    effective = resolve_collect_params(api_name, schema, **overrides)

    known_keys = sorted(set(default_params) | set(overrides))
    hints = {k: PARAM_HINTS[k] for k in known_keys if k in PARAM_HINTS}

    return {
        "api_name": api_name,
        "collect_mode": profile.mode,
        "collect_pattern": pattern.pattern_key,
        "default_params": default_params,
        "task_overrides": overrides,
        "effective_params": effective,
        "runtime_keys": runtime_keys,
        "editable_keys": [k for k in known_keys if k not in runtime_keys],
        "param_hints": hints,
    }


class CollectConfigService:
    async def get_for_task(self, session: AsyncSession, task_id: int) -> dict[str, Any]:
        task = await session.get(SyncTask, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        api_name, schema = await _schema_for_data_type_async(session, task.data_type)
        config = build_collect_config(
            api_name=api_name,
            schema=schema,
            task_overrides=task.collect_params,
        )
        config["task_id"] = task.id
        config["data_type"] = task.data_type
        return config

    def get_for_task_sync(self, session: Session, task: SyncTask) -> dict[str, Any]:
        api_name, schema = _schema_for_data_type_sync(session, task.data_type)
        config = build_collect_config(
            api_name=api_name,
            schema=schema,
            task_overrides=task.collect_params,
        )
        config["task_id"] = task.id
        config["data_type"] = task.data_type
        return config
