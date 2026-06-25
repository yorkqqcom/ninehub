"""Field name overrides — API / provider / global mapping to platform column keys.

Lookup order: api-level > provider-level > global canonical > global override > original.
See docs/DATA_NAMING_STANDARD.md §5.5.
"""

from __future__ import annotations

# Global identity mappings (multi-provider)
API_TO_CANONICAL_GLOBAL: dict[str, str] = {
    "ts_code": "stock_code",
    "symbol": "stock_code",
}

# Global reserved / ambiguous fields
GLOBAL_FIELD_OVERRIDES: dict[str, str] = {
    "change": "change_amount",
    "order": "sort_order",
    "user": "user_name",
}

# Provider-level overrides
PROVIDER_FIELD_OVERRIDES: dict[str, dict[str, str]] = {
    "akshare": {
        "symbol": "stock_code",
    },
}

# API-level overrides (highest priority; from legacy_schema_registry.json)
API_FIELD_OVERRIDES: dict[str, dict[str, str]] = {
    "daily": {"change": "change_amount"},
    "weekly": {"change": "change_amount"},
    "monthly": {"change": "change_amount"},
    "pro_bar": {"change": "change_amount"},
    "forecast": {"type": "fcst_type"},
    "fund_basic": {"type": "category_type"},
    "index_weight": {"con_code": "stock_code"},
    "index_member": {"con_code": "stock_code"},
}


def resolve_field_override(
    api_field: str,
    *,
    api_name: str | None = None,
    provider: str | None = "tushare",
) -> str:
    """Map api_field to platform column.key."""
    if api_name:
        api_map = API_FIELD_OVERRIDES.get(api_name) or {}
        if api_field in api_map:
            return api_map[api_field]
    if provider:
        provider_map = PROVIDER_FIELD_OVERRIDES.get(provider) or {}
        if api_field in provider_map:
            return provider_map[api_field]
    if api_field in API_TO_CANONICAL_GLOBAL:
        return API_TO_CANONICAL_GLOBAL[api_field]
    if api_field in GLOBAL_FIELD_OVERRIDES:
        return GLOBAL_FIELD_OVERRIDES[api_field]
    return api_field


def all_canonical_mappings(
    api_name: str | None = None,
    provider: str | None = "tushare",
) -> dict[str, str]:
    """Merged api_field -> column.key for schema building."""
    merged: dict[str, str] = {}
    merged.update(GLOBAL_FIELD_OVERRIDES)
    merged.update(API_TO_CANONICAL_GLOBAL)
    if provider:
        merged.update(PROVIDER_FIELD_OVERRIDES.get(provider) or {})
    if api_name:
        merged.update(API_FIELD_OVERRIDES.get(api_name) or {})
    return merged
