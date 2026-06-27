"""Resolve Tushare collect call params — never limit API columns via ``fields``."""

from __future__ import annotations

from typing import Any

# Full-market snapshot params (override stale L3 probe_params with ts_code/limit/SSE).
SNAPSHOT_FULL_MARKET_PARAMS: dict[str, dict[str, str]] = {
    "stock_basic": {"exchange": "", "list_status": "L"},
}

STOCK_BASIC_DEFAULT_FIELDS = (
    "ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,"
    "curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type"
)


def stock_basic_collect_fields(schema: dict[str, Any] | None = None) -> str:
    """Tushare default stock_basic omits exchange unless ``fields`` is set."""
    api_fields = list((schema or {}).get("api_fields") or [])
    if api_fields:
        return ",".join(api_fields)
    return STOCK_BASIC_DEFAULT_FIELDS

# Tushare default stock_basic payload omits exchange/delist_date unless ``fields`` is set.
_STOCK_BASIC_DEFAULT_API_FIELDS: tuple[str, ...] = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "fullname",
    "enname",
    "cnspell",
    "market",
    "exchange",
    "curr_type",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
    "act_name",
    "act_ent_type",
)


def stock_basic_fields_param(schema: dict[str, Any] | None = None) -> str:
    """Build explicit ``fields`` for stock_basic (full L3 columns, not probe subset)."""
    api_fields = [str(f) for f in ((schema or {}).get("api_fields") or []) if f]
    if not api_fields:
        api_fields = list(_STOCK_BASIC_DEFAULT_API_FIELDS)
    return ",".join(api_fields)


# Probe-only filters that must not leak into per-code or full-span backfill calls.
_ITERATION_PROBE_STRIP_KEYS = (
    "exchange",
    "ann_date",
    "period",
    "record_date",
    "ex_date",
    "imp_ann_date",
    "f_ann_date",
    "trade_date",
    "enddate",
    "pre_date",
    "actual_date",
    "modify_date",
)

# Financial period APIs: probe announcement windows must not combine with ``period``.
_PERIOD_PROBE_STRIP_KEYS = (
    "start_date",
    "end_date",
    "report_type",
    "comp_type",
)


def strip_iteration_probe_filters(params: dict[str, Any], *, mode: str) -> dict[str, Any]:
    """Drop probe filters when iterating ts_code or spanning a sync date window."""
    cleaned = dict(params)
    keys = list(_ITERATION_PROBE_STRIP_KEYS)
    if mode == "ts_code":
        keys.extend(("start_date", "end_date"))
    elif mode == "period":
        keys.extend(_PERIOD_PROBE_STRIP_KEYS)
    for key in keys:
        cleaned.pop(key, None)
    return cleaned


def sanitize_collect_params(params: dict[str, Any]) -> dict[str, Any]:
    """Drop probe-only filters so collect receives full API output."""
    cleaned = dict(params)
    cleaned.pop("fields", None)
    cleaned.pop("limit", None)
    cleaned.pop("ts_code", None)
    for key in (
        "max_codes_per_run",
        "max_api_calls_per_run",
        "batch_size",
        "mode",
        "pattern",
    ):
        cleaned.pop(key, None)
    return cleaned


def resolve_collect_params(
    api_name: str,
    schema: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    from app.services.tia.collect_pattern import resolve_probe_params_for_api

    if api_name in SNAPSHOT_FULL_MARKET_PARAMS:
        params = dict(SNAPSHOT_FULL_MARKET_PARAMS[api_name])
        if api_name == "stock_basic":
            params["fields"] = stock_basic_collect_fields(schema)
    else:
        params = sanitize_collect_params(resolve_probe_params_for_api(api_name, schema))
    params.update(overrides)
    return params