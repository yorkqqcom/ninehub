"""Unique key & index registry — single source for L3 DDL, upsert, and preflight.

Pipeline alignment (审批 → 建表 → 采集 → 代码):
  infer_schema   → schema.unique_keys + schema.indexes + unique_constraint
  run_migration  → UNIQUE constraint + browse indexes (ix_*)
  register_handler / collect → TiaDataLoader uses same unique_keys
  catalog / standards API → expose keys for UI & checklist
"""

from __future__ import annotations

from typing import Any

from app.services.catalog.canonical_standard import canonical_key, normalize_unique_keys

# API 级显式唯一键（canonical 列名）；优先于字段启发式（防 trade_cal 类误配）
API_UNIQUE_KEY_OVERRIDES: dict[str, list[str]] = {
    "trade_cal": ["exchange", "cal_date"],
    "stock_basic": ["stock_code"],
    "daily": ["stock_code", "trade_date"],
    "daily_basic": ["stock_code", "trade_date"],
    "weekly": ["stock_code", "trade_date"],
    "monthly": ["stock_code", "trade_date"],
    "income": ["stock_code", "end_date"],
    "balancesheet": ["stock_code", "end_date"],
    "cashflow": ["stock_code", "end_date"],
    "fina_indicator": ["stock_code", "end_date"],
    "fina_forecast": ["stock_code", "end_date"],
    "express": ["stock_code", "end_date"],
    "index_daily": ["stock_code", "trade_date"],
    "share_float": ["stock_code", "ann_date"],
    "dividend": ["stock_code", "end_date"],
    "top_list": ["stock_code", "trade_date"],
    "top_inst": ["stock_code", "trade_date"],
    "moneyflow": ["stock_code", "trade_date"],
    "adj_factor": ["stock_code", "trade_date"],
    "margin_secs": ["stock_code", "trade_date", "exchange"],
    "stk_managers": ["stock_code", "title", "begin_date"],
    "stk_rewards": ["stock_code", "end_date", "title"],
    # con_code → stock_code at load time; heuristic misses ts_code/stock_code in api_fields
    "index_weight": ["index_code", "stock_code", "trade_date"],
    "index_member": ["index_code", "stock_code"],
}

# 浏览/筛选常用列 → 非唯一索引（加速 DataBrowse 按代码/日期过滤）
BROWSE_INDEX_COLUMNS = (
    "stock_code",
    "trade_date",
    "cal_date",
    "end_date",
    "ann_date",
    "exchange",
)


def resolve_unique_keys(api_name: str, api_fields: list[str]) -> list[str]:
    """Resolve business unique keys for upsert (canonical column names)."""
    override = API_UNIQUE_KEY_OVERRIDES.get(api_name)
    if override:
        return list(override)
    return normalize_unique_keys(api_fields)


def unique_constraint_name(table_name: str, unique_keys: list[str]) -> str:
    return f"uq_{table_name}_{'_'.join(unique_keys)}"


def build_schema_indexes(schema: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    """Build index metadata: one unique (upsert) + optional browse filters."""
    unique_keys = list(schema.get("unique_keys") or [])
    col_keys = {c["key"] for c in schema.get("columns", [])}
    indexes: list[dict[str, Any]] = []

    if unique_keys and all(k in col_keys for k in unique_keys):
        indexes.append(
            {
                "name": unique_constraint_name(table_name, unique_keys),
                "columns": unique_keys,
                "unique": True,
                "purpose": "upsert",
            }
        )

    for col in BROWSE_INDEX_COLUMNS:
        if col not in col_keys:
            continue
        idx_name = f"ix_{table_name}_{col}"
        if any(i["name"] == idx_name for i in indexes):
            continue
        indexes.append(
            {
                "name": idx_name,
                "columns": [col],
                "unique": False,
                "purpose": "browse_filter",
            }
        )
    return indexes


def enrich_schema_keys(
    schema: dict[str, Any],
    api_name: str,
    *,
    table_name: str | None = None,
) -> dict[str, Any]:
    """Persist unique_keys, nullability, indexes, and constraint name into schema."""
    api_fields = list(schema.get("api_fields") or [])
    unique_keys = resolve_unique_keys(api_name, api_fields)
    schema["unique_keys"] = unique_keys

    for col in schema.get("columns", []):
        col["nullable"] = col["key"] not in unique_keys

    tn = table_name
    if not tn:
        from app.services.tia.constants import api_to_table_name

        tn = api_to_table_name(api_name)
    indexes = build_schema_indexes(schema, tn)
    schema["indexes"] = indexes
    uq = next((i for i in indexes if i.get("purpose") == "upsert"), None)
    if uq:
        schema["unique_constraint"] = {
            "name": uq["name"],
            "columns": uq["columns"],
        }
    return schema


def validate_unique_key_columns(schema: dict[str, Any]) -> list[str]:
    """DDL/upsert readiness checks for unique key columns."""
    errors: list[str] = []
    col_by_key = {c["key"]: c for c in schema.get("columns", [])}
    unique_keys = schema.get("unique_keys") or []
    if not unique_keys:
        errors.append("schema.unique_keys is empty")
        return errors

    for uk in unique_keys:
        col = col_by_key.get(uk)
        if col is None:
            errors.append(f"unique_key '{uk}' not in columns")
        elif col.get("nullable", True):
            errors.append(f"unique_key column '{uk}' must be NOT NULL")

    mappings = schema.get("field_mappings") or {}
    for uk in unique_keys:
        api_aliases = [api_f for api_f, ck in mappings.items() if ck == uk]
        if not api_aliases and uk not in (schema.get("api_fields") or []):
            errors.append(f"unique_key '{uk}' has no API field mapping")
    return errors


def probe_columns_cover_unique_keys(
    schema: dict[str, Any],
    probe_field_names: list[str],
) -> tuple[bool, list[str]]:
    """Check live probe columns can populate all unique keys (after canonical mapping)."""
    unique_keys = schema.get("unique_keys") or []
    mappings = schema.get("field_mappings") or {}
    probe_set = set(probe_field_names)
    missing: list[str] = []
    for uk in unique_keys:
        api_field = next((af for af, ck in mappings.items() if ck == uk), uk)
        canon = canonical_key(api_field)
        if api_field not in probe_set and canon not in probe_set and uk not in probe_set:
            missing.append(uk)
    return len(missing) == 0, missing


def is_registry_registered(api_name: str) -> bool:
    """True when api_name has explicit entry in API_UNIQUE_KEY_OVERRIDES."""
    return api_name in API_UNIQUE_KEY_OVERRIDES


def build_registry_hint(api_name: str, api_fields: list[str] | None = None) -> dict[str, Any]:
    """Suggest code snippet for unique_key_registry.py registration."""
    from app.services.catalog.canonical_standard import resolve_api_fields

    fields = api_fields or resolve_api_fields(api_name)
    heuristic_keys = normalize_unique_keys(fields)
    registered_keys = API_UNIQUE_KEY_OVERRIDES.get(api_name)
    suggested = registered_keys or heuristic_keys
    keys_repr = ", ".join(f'"{k}"' for k in suggested)
    snippet = f'    "{api_name}": [{keys_repr}],'
    return {
        "api_name": api_name,
        "registry_registered": is_registry_registered(api_name),
        "heuristic_unique_keys": heuristic_keys,
        "registered_unique_keys": list(registered_keys) if registered_keys else None,
        "suggested_unique_keys": list(suggested),
        "registry_snippet": snippet,
        "registry_file": "backend/app/services/tia/unique_key_registry.py",
    }
