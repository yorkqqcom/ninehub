"""Infer TIA fact-table schema from probe metadata and API fields."""

from __future__ import annotations

from typing import Any

from app.catalog.tia_probe_registry import api_probe_meta, resolve_probe_params
from app.schemas.catalog import CatalogColumnMeta, CatalogFilterMeta

_DATE_FIELDS = frozenset(
    {"trade_date", "end_date", "ann_date", "list_date", "pre_date", "cal_date", "date"}
)
_CODE_FIELDS = frozenset({"ts_code", "stock_code", "index_code", "fund_code", "symbol"})
_NUMBER_HINTS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "revenue",
        "total_assets",
        "total_liab",
        "pe",
        "pb",
        "turnover_rate",
        "float_share",
    }
)
_TEXT_FIELDS = frozenset(
    {
        "introduction",
        "main_business",
        "business_scope",
        "desc",
        "description",
        "reason",
        "change_reason",
        "content",
        "summary",
        "holder_name",
    }
)


def _infer_column_type(field: str) -> str:
    if field in _TEXT_FIELDS:
        return "text"
    if field in _DATE_FIELDS or field.endswith("_date"):
        return "date"
    if field in _NUMBER_HINTS or field.endswith(("_vol", "_amount", "_ratio", "_rate")):
        return "number"
    return "string"


def _field_label(field: str) -> str:
    labels = {
        "ts_code": "代码",
        "trade_date": "交易日",
        "end_date": "报告期",
        "ann_date": "公告日",
        "name": "名称",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "vol": "成交量",
        "amount": "成交额",
    }
    return labels.get(field, field)


def infer_unique_keys(fields: list[str]) -> list[str]:
    from app.services.catalog.canonical_standard import normalize_unique_keys

    return normalize_unique_keys(fields)


def infer_schema_from_fields(
    fields: list[str],
    *,
    probe_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build override_json.schema payload."""
    columns = [
        {
            "key": f,
            "label": _field_label(f),
            "type": _infer_column_type(f),
            "nullable": f not in infer_unique_keys(fields),
        }
        for f in fields
    ]
    schema: dict[str, Any] = {
        "columns": columns,
        "unique_keys": infer_unique_keys(fields),
    }
    if probe_params:
        schema["probe_params"] = probe_params
    schema.setdefault(
        "collect",
        {"max_codes_per_run": 50, "max_api_calls_per_run": 200},
    )
    return schema


def infer_schema_for_api(
    api_name: str,
    *,
    actual_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve canonical schema from catalog probe meta or live probe fields."""
    from app.services.catalog.canonical_standard import build_canonical_schema

    return build_canonical_schema(api_name, actual_fields=actual_fields)


def schema_to_catalog_columns(schema: dict[str, Any]) -> list[CatalogColumnMeta]:
    return [
        CatalogColumnMeta(key=c["key"], label=c.get("label", c["key"]), type=c.get("type", "string"))
        for c in schema.get("columns", [])
    ]


def schema_to_catalog_filters(schema: dict[str, Any]) -> list[CatalogFilterMeta]:
    keys = {c["key"] for c in schema.get("columns", [])}
    filters: list[CatalogFilterMeta] = []
    if "ts_code" in keys or "stock_code" in keys:
        filters.append(
            CatalogFilterMeta(key="stock_code", label="股票代码", filter_type="stock_picker")
        )
    date_key = next(
        (k for k in ("trade_date", "cal_date", "end_date", "ann_date") if k in keys),
        None,
    )
    if date_key:
        filters.append(CatalogFilterMeta(key=date_key, label="日期范围", filter_type="date_range"))
    return filters
