"""Canonical data standard — single source of truth for DDL, catalog, and checklist."""

from __future__ import annotations

from typing import Any

from app.catalog.field_override_registry import (
    API_TO_CANONICAL_GLOBAL,
    resolve_field_override,
)
from app.catalog.tia_probe_registry import api_probe_meta, resolve_probe_params
from app.schemas.catalog import CatalogColumnMeta
from app.services.tia.schema_inference import _field_label, _infer_column_type

# Backward-compatible alias for tests and imports
API_TO_CANONICAL: dict[str, str] = dict(API_TO_CANONICAL_GLOBAL)

CANONICAL_TO_API: dict[str, str] = {v: k for k, v in API_TO_CANONICAL.items()}

STANDARD_VERSION = 1


def _doc_expected_fields(
    api_name: str,
    live_fields: list[str] | None,
    actual_fields: list[str] | None,
) -> list[str]:
    if not (live_fields or actual_fields):
        return []
    from app.services.catalog.field_resolution import resolve_expected_fields

    return resolve_expected_fields(api_name)


def canonical_key(
    field: str,
    *,
    api_name: str | None = None,
    provider: str | None = "tushare",
) -> str:
    return resolve_field_override(field, api_name=api_name, provider=provider)


def api_field_for_column(column_key: str) -> str:
    return CANONICAL_TO_API.get(column_key, column_key)


def normalize_unique_keys(fields: list[str]) -> list[str]:
    """Heuristic unique keys using canonical column names."""
    canon = {canonical_key(f) for f in fields}
    raw = set(fields)
    if "stock_code" in canon or "ts_code" in raw:
        code = "stock_code"
        if "trade_date" in canon or "trade_date" in raw:
            return [code, "trade_date"]
        if "end_date" in canon or "end_date" in raw:
            return [code, "end_date"]
        if "ann_date" in canon or "ann_date" in raw:
            return [code, "ann_date"]
        return [code]
    if "trade_date" in canon or "trade_date" in raw:
        return ["trade_date"]
    if ("cal_date" in canon or "cal_date" in raw) and ("exchange" in canon or "exchange" in raw):
        return ["exchange", "cal_date"]
    if "cal_date" in canon or "cal_date" in raw:
        return ["cal_date"]
    if fields:
        return [canonical_key(fields[0])]
    return ["id"]


def resolve_api_fields(
    api_name: str,
    actual_fields: list[str] | None = None,
    *,
    live_fields: list[str] | None = None,
    require_live_actual: bool = False,
) -> list[str]:
    from app.services.catalog.field_resolution import resolve_api_fields as _resolve

    return _resolve(
        api_name,
        actual_fields,
        live_fields=live_fields,
        require_live_actual=require_live_actual,
    )


def resolve_probe_status(api_name: str, probe_category: str | None) -> str:
    meta_probe = (api_probe_meta(api_name) or {}).get("probe") or {}
    if meta_probe.get("expected_fields"):
        return "configured"
    from app.catalog.tia_probe_registry import OFFICIAL_ONLY_API_PROBES

    oo = (OFFICIAL_ONLY_API_PROBES.get(api_name) or {}).get("probe") or {}
    if oo.get("expected_fields"):
        return "configured"
    if probe_category and probe_category != "none":
        from app.services.tia.scan.probe_templates import PROBE_TEMPLATES

        tpl = PROBE_TEMPLATES.get(probe_category) or {}
        if tpl.get("expected_fields"):
            return "template"
    return "unconfigured"


def is_approved_standard(schema: dict[str, Any] | None) -> bool:
    if not schema:
        return False
    ds = schema.get("data_standard") or {}
    return bool(ds.get("approved")) and bool(schema.get("field_mappings"))


def build_canonical_schema(
    api_name: str,
    *,
    actual_fields: list[str] | None = None,
    live_fields: list[str] | None = None,
    existing_schema: dict[str, Any] | None = None,
    require_live_actual: bool = False,
) -> dict[str, Any]:
    """Build platform canonical schema from API probe fields."""
    api_fields = resolve_api_fields(
        api_name,
        actual_fields,
        live_fields=live_fields,
        require_live_actual=require_live_actual,
    )
    if not api_fields:
        from app.core.exceptions import ValidationError

        raise ValidationError(f"No probe fields configured for api '{api_name}'")
    meta = api_probe_meta(api_name) or {}
    probe = meta.get("probe") or {}
    raw_params = dict(probe.get("params") or {})
    if not raw_params:
        from app.services.tia.scan.probe_planner import resolve_probe_spec

        spec, _, _ = resolve_probe_spec(api_name)
        if spec:
            raw_params = dict(spec.get("params") or {})
    probe_params = resolve_probe_params(raw_params) if raw_params else None

    field_mappings: dict[str, str] = {}
    columns: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for api_field in api_fields:
        col_key = canonical_key(api_field, api_name=api_name)
        field_mappings[api_field] = col_key
        if col_key in seen_keys:
            continue
        seen_keys.add(col_key)
        columns.append(
            {
                "key": col_key,
                "label": _field_label(api_field),
                "type": _infer_column_type(api_field),
                "nullable": True,
                "api_field": api_field,
            }
        )

    unique_keys = normalize_unique_keys(api_fields)
    for col in columns:
        col["nullable"] = col["key"] not in unique_keys

    schema: dict[str, Any] = {
        "columns": columns,
        "unique_keys": unique_keys,
        "field_mappings": field_mappings,
        "api_fields": api_fields,
        "standard_version": STANDARD_VERSION,
        "built_from": (
            "live_actual"
            if actual_fields or live_fields
            else "catalog_fallback"
        ),
        "field_sources": {
            "live_fields": list(live_fields or []),
            "explicit_actual_fields": list(actual_fields or []),
            "doc_expected_fields": _doc_expected_fields(api_name, live_fields, actual_fields),
        },
        "data_standard": {
            "approved": True,
            "api_name": api_name,
            "coverage_pct": 100.0,
            "missing_count": 0,
            "extra_count": 0,
            "type_mismatch_count": 0,
        },
    }
    if probe_params:
        schema["probe_params"] = probe_params
    if existing_schema and existing_schema.get("probe_params"):
        schema["probe_params"] = existing_schema["probe_params"]
    from app.services.tia.unique_key_registry import enrich_schema_keys

    return enrich_schema_keys(schema, api_name)


def resolve_schema_for_ddl(
    api_name: str,
    override_schema: dict[str, Any] | None = None,
    *,
    actual_fields: list[str] | None = None,
    live_fields: list[str] | None = None,
    force_rebuild: bool = False,
    require_live_actual: bool = False,
) -> dict[str, Any]:
    """Schema used for run_migration — approved canonical or freshly built."""
    if (
        not force_rebuild
        and override_schema
        and is_approved_standard(override_schema)
        and override_schema.get("columns")
    ):
        return override_schema
    return build_canonical_schema(
        api_name,
        actual_fields=actual_fields,
        live_fields=live_fields,
        existing_schema=override_schema,
        require_live_actual=require_live_actual,
    )


def validate_canonical_for_ddl(schema: dict[str, Any], api_name: str) -> list[str]:
    """Return validation error messages; empty list means OK to create table."""
    errors: list[str] = []
    api_fields = schema.get("api_fields") or resolve_api_fields(api_name)
    mappings = schema.get("field_mappings") or {}
    columns = schema.get("columns") or []
    col_keys = {c["key"] for c in columns}
    unique_keys = schema.get("unique_keys") or []

    if not columns:
        errors.append("schema.columns is empty")
    if not unique_keys:
        errors.append("schema.unique_keys is empty")

    for api_field in api_fields:
        if api_field not in mappings:
            errors.append(f"API field '{api_field}' has no field_mappings entry")
            continue
        target = mappings[api_field]
        if target not in col_keys:
            errors.append(f"field_mappings[{api_field}] -> '{target}' not in columns")

    for uk in unique_keys:
        if uk not in col_keys:
            errors.append(f"unique_key '{uk}' not in columns")

    ds = schema.get("data_standard") or {}
    if ds.get("missing_count", 0) > 0:
        errors.append(f"data standard has {ds['missing_count']} missing field(s)")
    if ds.get("type_mismatch_count", 0) > 0:
        errors.append(f"data standard has {ds['type_mismatch_count']} type mismatch(es)")
    if not ds.get("approved"):
        errors.append("data standard is not approved for DDL")

    from app.services.tia.unique_key_registry import validate_unique_key_columns

    errors.extend(validate_unique_key_columns(schema))

    indexes = schema.get("indexes") or []
    for idx in indexes:
        for col in idx.get("columns") or []:
            if col not in col_keys:
                errors.append(f"index '{idx.get('name')}' references unknown column '{col}'")

    return errors


def schema_to_catalog_columns(schema: dict[str, Any]) -> list[CatalogColumnMeta]:
    return [
        CatalogColumnMeta(key=c["key"], label=c.get("label", c["key"]), type=c.get("type", "string"))
        for c in schema.get("columns", [])
    ]


def build_checklist_from_schema(schema: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Field-level checklist derived from canonical schema (always aligned when built fresh)."""
    api_fields = schema.get("api_fields") or []
    mappings = schema.get("field_mappings") or {}
    col_by_key = {c["key"]: c for c in schema.get("columns", [])}
    unique_keys = set(schema.get("unique_keys") or [])

    fields: list[dict[str, Any]] = []
    matched_keys: set[str] = set()

    for api_field in api_fields:
        col_key = mappings.get(api_field, canonical_key(api_field))
        col = col_by_key.get(col_key)
        inferred = _infer_column_type(api_field)
        if col:
            matched_keys.add(col_key)
            status = "matched" if col.get("type", "string") == inferred or api_field != col_key else "matched"
            if col.get("type", "string") != inferred and api_field == col.get("api_field", api_field):
                status = "type_mismatch"
            fields.append(
                {
                    "api_field": api_field,
                    "standard_key": col_key,
                    "standard_label": col.get("label", col_key),
                    "standard_type": col.get("type", "string"),
                    "inferred_type": inferred,
                    "status": status,
                    "is_unique_key": col_key in unique_keys,
                }
            )
        else:
            fields.append(
                {
                    "api_field": api_field,
                    "inferred_type": inferred,
                    "status": "missing_in_standard",
                    "is_unique_key": False,
                }
            )

    extra_fields: list[dict[str, Any]] = []
    mapped_targets = set(mappings.values())
    for col in schema.get("columns", []):
        key = col["key"]
        if key in matched_keys:
            continue
        if key in mapped_targets:
            continue
        extra_fields.append(
            {
                "api_field": key,
                "standard_key": key,
                "standard_label": col.get("label", key),
                "standard_type": col.get("type", "string"),
                "inferred_type": _infer_column_type(key),
                "status": "extra_in_standard",
                "is_unique_key": key in unique_keys,
            }
        )

    matched = sum(1 for f in fields if f["status"] == "matched")
    missing = sum(1 for f in fields if f["status"] == "missing_in_standard")
    type_mismatch = sum(1 for f in fields if f["status"] == "type_mismatch")
    extra = len(extra_fields)
    api_count = len(api_fields)
    coverage = round(matched / api_count * 100, 1) if api_count else 0.0

    counts = {
        "api_field_count": api_count,
        "standard_field_count": len(schema.get("columns", [])),
        "matched_count": matched,
        "missing_count": missing,
        "extra_count": extra,
        "type_mismatch_count": type_mismatch,
        "coverage_pct": coverage,
    }
    return fields, extra_fields, counts


def _field_mapping_priority(api_field: str) -> tuple[int, str]:
    """Prefer ts_code when several API fields map to the same canonical column."""
    if api_field == "ts_code":
        return (0, api_field)
    return (1, api_field)


def apply_dataframe_field_mappings(df, schema: dict[str, Any]):
    """Rename API columns to canonical schema keys before upsert."""
    import pandas as pd

    if df is None or df.empty:
        return df
    mappings = schema.get("field_mappings") or {}
    rename: dict[str, str] = {}
    claimed_targets: set[str] = set()
    ordered = sorted(mappings.items(), key=lambda item: _field_mapping_priority(item[0]))
    for api_field, col_key in ordered:
        if api_field not in df.columns or api_field == col_key:
            continue
        if col_key in claimed_targets or col_key in df.columns:
            continue
        rename[api_field] = col_key
        claimed_targets.add(col_key)
    if rename:
        df = df.rename(columns=rename)
    return df
