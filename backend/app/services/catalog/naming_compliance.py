"""Naming compliance audit for data standards (L1–L3)."""

from __future__ import annotations

import re

from app.services.tia.constants import (
    DEFAULT_PROVIDER,
    api_to_data_type,
    api_to_table_name,
    is_legacy_data_type,
    legacy_data_type,
)
from app.services.tia.unique_key_registry import is_registry_registered

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED_PLATFORM_COLUMNS = frozenset({"ts_code", "change", "type"})


def resolve_provider_id(data_type: str, api_name: str) -> str:
    """Infer provider_id from data_type and api_name."""
    if is_legacy_data_type(data_type):
        return DEFAULT_PROVIDER
    suffix = f"_{api_name}"
    if data_type.endswith(suffix):
        prefix = data_type[: -len(suffix)]
        if prefix:
            return prefix
    return DEFAULT_PROVIDER


def resolve_table_name(
    api_name: str,
    data_type: str,
    *,
    override_table_name: str | None = None,
    provider_id: str | None = None,
) -> str:
    if override_table_name:
        return override_table_name
    provider = provider_id or resolve_provider_id(data_type, api_name)
    return api_to_table_name(api_name, provider)


def audit_naming_compliance(
    *,
    api_name: str,
    data_type: str,
    table_name: str,
    provider_id: str,
    schema: dict | None,
) -> dict:
    """Return {score, issues[]} for naming standard checklist."""
    issues: list[str] = []
    canonical_dt = api_to_data_type(api_name, provider_id)
    legacy_dt = legacy_data_type(api_name)

    if data_type not in (canonical_dt, legacy_dt):
        issues.append(
            f"data_type '{data_type}' 应为 '{canonical_dt}'（legacy 别名 '{legacy_dt}' 只读兼容）"
        )

    expected_table = api_to_table_name(api_name, provider_id)
    if table_name != expected_table and table_name != data_type:
        issues.append(
            f"table_name '{table_name}' 默认应等于 data_type 或 '{expected_table}'"
        )

    if schema:
        api_fields = schema.get("api_fields") or []
        mappings = schema.get("field_mappings") or {}
        for col in schema.get("columns") or []:
            key = col.get("key") or ""
            if not _SNAKE_CASE.match(key):
                issues.append(f"列 key '{key}' 不符合 snake_case")
            if key in _RESERVED_PLATFORM_COLUMNS:
                issues.append(f"列 key '{key}' 为保留字，须经 field_override_registry 映射")

        if "ts_code" in api_fields and mappings.get("ts_code") != "stock_code":
            issues.append("ts_code 须映射为 stock_code")

        if api_fields and not is_registry_registered(api_name):
            issues.append(
                f"API '{api_name}' 未在 unique_key_registry.py 登记唯一键（建议 L3 前补登记）"
            )

    score = max(0, 100 - min(100, len(issues) * 15))
    return {"score": score, "issues": issues}
