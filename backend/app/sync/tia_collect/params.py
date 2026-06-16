"""Resolve Tushare collect call params — never limit API columns via ``fields``."""

from __future__ import annotations

from typing import Any

# Full-market snapshot params (override stale L3 probe_params with ts_code/limit/SSE).
SNAPSHOT_FULL_MARKET_PARAMS: dict[str, dict[str, str]] = {
    "stock_basic": {"exchange": "", "list_status": "L"},
}


def sanitize_collect_params(params: dict[str, Any]) -> dict[str, Any]:
    """Drop probe-only filters so collect receives full API output."""
    cleaned = dict(params)
    cleaned.pop("fields", None)
    cleaned.pop("limit", None)
    cleaned.pop("ts_code", None)
    return cleaned


def resolve_collect_params(
    api_name: str,
    schema: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    from app.services.tia.collect_pattern import resolve_probe_params_for_api

    if api_name in SNAPSHOT_FULL_MARKET_PARAMS:
        params = dict(SNAPSHOT_FULL_MARKET_PARAMS[api_name])
    else:
        params = sanitize_collect_params(resolve_probe_params_for_api(api_name, schema))
    params.update(overrides)
    return params