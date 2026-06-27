"""Collect pattern inference — probe param shape → sync strategy mode.

Prevents misclassification like trade_cal (catalog probe_category=trade_date
but actual probe uses exchange+date_range → must be exchange_date_range mode).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

# Iteration registry: pattern key → sync mode + human-readable metadata
COLLECT_PATTERN_REGISTRY: dict[str, dict[str, str]] = {
    "exchange_date_range": {
        "mode": "exchange_date_range",
        "label": "交易所+日期区间（单次拉取）",
        "api_calls_hint": "1 次/运行",
        "risk": "若误配为 trade_date 将按交易日循环，极易超预算",
    },
    "ts_code_date_range": {
        "mode": "date_range",
        "label": "股票代码+日期区间",
        "api_calls_hint": "股票数 × 1",
        "risk": "全市场同步时受 max_codes_per_run 限制",
    },
    "trade_date": {
        "mode": "trade_date",
        "label": "按交易日逐日拉取",
        "api_calls_hint": "区间内交易日数",
        "risk": "长区间首次同步可能超 200 次预算",
    },
    "period_financial": {
        "mode": "period",
        "label": "财报期",
        "api_calls_hint": "股票数 × 报告期数",
        "risk": "全市场 × 多期可能超预算",
    },
    "ts_code": {
        "mode": "ts_code",
        "label": "单代码",
        "api_calls_hint": "股票数",
        "risk": "全市场同步受 max_codes_per_run 限制",
    },
    "list_basic": {
        "mode": "snapshot",
        "label": "全量列表快照",
        "api_calls_hint": "1 次/运行",
        "risk": "",
    },
    "list_limit": {
        "mode": "snapshot",
        "label": "限量快照",
        "api_calls_hint": "1 次/运行",
        "risk": "",
    },
    "index_daily": {
        "mode": "date_range",
        "label": "指数+日期区间",
        "api_calls_hint": "指数数 × 1",
        "risk": "",
    },
    "generic": {
        "mode": "generic",
        "label": "通用单次探针",
        "api_calls_hint": "1 次/运行",
        "risk": "",
    },
    "file_import": {
        "mode": "file_import",
        "label": "TDX vipdoc 文件导入",
        "api_calls_hint": "文件批次数",
        "risk": "需配置 Sidecar install_root / vipdoc",
    },
    "tdx_concept_snapshot": {
        "mode": "tdx_concept_snapshot",
        "label": "TDX 概念快照",
        "api_calls_hint": "1 次/运行",
        "risk": "",
    },
}

# APIs where param inference is insufficient (business override)
API_PATTERN_OVERRIDES: dict[str, str] = {
    "share_float": "ts_code",
    "trade_cal": "exchange_date_range",
    "margin_secs": "trade_date",
    "bar_1d": "file_import",
    "bar_1m": "file_import",
    "bar_5m": "file_import",
    "concept_index": "tdx_concept_snapshot",
    "concept_member": "tdx_concept_snapshot",
}

# Reference APIs per pattern (documentation + regression tests)
PATTERN_EXAMPLE_APIS: dict[str, list[str]] = {
    "exchange_date_range": ["trade_cal"],
    "ts_code_date_range": ["daily", "weekly", "monthly"],
    "trade_date": ["top_list", "margin", "block_trade"],
    "period_financial": ["income", "balancesheet"],
    "list_basic": ["stock_basic"],
    "ts_code": ["share_float"],
}


@dataclass(frozen=True)
class CollectPatternResult:
    pattern_key: str
    mode: str
    label: str
    api_calls_hint: str
    probe_spec_source: str | None = None
    catalog_probe_category: str | None = None
    pattern_mismatch: bool = False
    warnings: tuple[str, ...] = ()
    estimated_calls_per_year: int | None = None


@dataclass
class CollectPatternValidation:
    result: CollectPatternResult
    blocking_errors: list[str] = field(default_factory=list)


def _param_keys(params: dict[str, Any]) -> set[str]:
    return set(params.keys())


def infer_collect_pattern(
    params: dict[str, Any],
    *,
    expected_fields: list[str] | None = None,
) -> str:
    """Infer collect pattern from resolved probe params (priority-ordered)."""
    keys = _param_keys(params)
    has_ts = "ts_code" in keys
    has_start = "start_date" in keys
    has_end = "end_date" in keys
    has_trade_date = "trade_date" in keys
    has_exchange = "exchange" in keys
    has_period = "period" in keys
    has_list_status = "list_status" in keys
    has_limit = "limit" in keys

    fields = set(expected_fields or [])
    has_cal_date = "cal_date" in fields

    # exchange + date range, no per-code iteration
    if has_exchange and has_start and has_end and not has_ts:
        return "exchange_date_range"
    if has_cal_date and has_start and has_end and not has_ts and not has_trade_date:
        return "exchange_date_range"

    if has_ts and has_start and has_end:
        if params.get("ts_code", "").endswith(".SH") and "index" in fields:
            return "index_daily"
        return "ts_code_date_range"

    if has_ts and has_period:
        return "period_financial"

    if has_trade_date and not has_ts and not (has_start and has_end):
        return "trade_date"

    if has_ts and len(keys) <= 2:
        return "ts_code"

    if has_list_status or (has_exchange and not has_ts and not has_start):
        return "list_basic"

    if has_limit and not has_ts:
        return "list_limit"

    return "generic"


def _catalog_probe_category(api_name: str) -> str | None:
    from app.services.tia.scan.tushare_doc_registry import load_api_by_doc_id

    for row in load_api_by_doc_id().values():
        if row.get("api") == api_name:
            return row.get("probe_category")
    return None


def _official_entry_for_api(api_name: str) -> Any | None:
    from app.services.tia.scan.index_loader import load_bundled_index
    from app.services.tia.scan.tushare_doc_registry import load_api_by_doc_id, resolve_api_meta
    from app.services.tia.scan.types import OfficialApiEntry

    bundled = load_bundled_index("tdx")
    for entry in bundled.apis:
        if entry.api == api_name:
            return entry
    for row in load_api_by_doc_id().values():
        if row.get("api") == api_name:
            return OfficialApiEntry.from_dict(row)
    meta = resolve_api_meta(api_name)
    if meta:
        return OfficialApiEntry.from_dict(meta)
    return None


def _mode_for_probe_category(category: str | None) -> str | None:
    if not category:
        return None
    entry = COLLECT_PATTERN_REGISTRY.get(category)
    return entry["mode"] if entry else None


def estimate_calls_for_pattern(
    pattern_key: str,
    *,
    sync_start: date | None = None,
    sync_end: date | None = None,
    max_codes: int = 50,
) -> int | None:
    """Rough API call estimate for first full sync (budget preview)."""
    start = sync_start or date(2019, 1, 1)
    end = sync_end or date.today()
    if pattern_key in ("exchange_date_range", "list_basic", "list_limit", "generic"):
        return 1
    if pattern_key == "trade_date":
        days = 0
        d = start
        while d <= end:
            if d.weekday() < 5:
                days += 1
            d += timedelta(days=1)
        return max(1, int(days * 0.69))  # ~250/365 trading days
    if pattern_key in ("ts_code_date_range", "ts_code", "period_financial", "index_daily"):
        return max_codes
    return None


def estimate_calls_per_run(
    pattern_key: str,
    *,
    max_codes_per_run: int = 50,
    max_api_calls_per_run: int = 200,
) -> int:
    """Single collect run estimate for L3 preflight (not full-history backfill)."""
    if pattern_key in ("exchange_date_range", "list_basic", "list_limit", "generic"):
        return 1
    if pattern_key == "trade_date":
        return 1
    if pattern_key in ("ts_code_date_range", "ts_code", "period_financial", "index_daily"):
        return min(max_codes_per_run, max_api_calls_per_run)
    return 1


def resolve_collect_pattern(
    api_name: str,
    official_entry: Any | None = None,
) -> CollectPatternResult:
    """Resolve collect pattern from actual probe spec (not catalog label alone)."""
    from app.services.tia.scan.probe_planner import resolve_probe_spec

    if official_entry is None:
        official_entry = _official_entry_for_api(api_name)
    if api_name in API_PATTERN_OVERRIDES:
        pattern_key = API_PATTERN_OVERRIDES[api_name]
        spec, source, _ = resolve_probe_spec(api_name, official_entry)
        params = (spec or {}).get("params") or {}
        expected = (spec or {}).get("expected_fields") or []
        inferred_from_params = infer_collect_pattern(params, expected_fields=expected)
        catalog_cat = _catalog_probe_category(api_name)
        catalog_mode = _mode_for_probe_category(catalog_cat)
        result_mode = COLLECT_PATTERN_REGISTRY[pattern_key]["mode"]
        mismatch = bool(catalog_mode and catalog_mode != result_mode)
        warnings: list[str] = []
        if inferred_from_params != pattern_key:
            warnings.append(
                f"参数推断为 {inferred_from_params}，业务覆盖为 {pattern_key}"
            )
        if mismatch:
            warnings.append(
                f"catalog probe_category={catalog_cat} → mode={catalog_mode}，"
                f"已覆盖为 pattern={pattern_key} → mode={result_mode}"
            )
        return _build_result(
            pattern_key,
            probe_spec_source=source,
            catalog_probe_category=catalog_cat,
            pattern_mismatch=mismatch,
            extra_warnings=tuple(warnings),
        )

    spec, source, _ = resolve_probe_spec(api_name, official_entry)
    params = (spec or {}).get("params") or {}
    expected = (spec or {}).get("expected_fields") or []
    pattern_key = infer_collect_pattern(params, expected_fields=expected)
    catalog_cat = _catalog_probe_category(api_name)

    warnings: list[str] = []
    mismatch = False
    catalog_mode = _mode_for_probe_category(catalog_cat)
    result_mode = COLLECT_PATTERN_REGISTRY[pattern_key]["mode"]
    if catalog_mode and catalog_mode != result_mode:
        mismatch = True
        warnings.append(
            f"catalog probe_category={catalog_cat} → mode={catalog_mode}，"
            f"探针参数推断 pattern={pattern_key} → mode={result_mode}"
        )
        if catalog_mode == "trade_date" and result_mode == "exchange_date_range":
            warnings.append(
                "高风险：类似 trade_cal，catalog 标为 trade_date 但实际为交易所日历区间接口"
            )

    return _build_result(
        pattern_key,
        probe_spec_source=source,
        catalog_probe_category=catalog_cat,
        pattern_mismatch=mismatch,
        extra_warnings=tuple(warnings),
    )


def _build_result(
    pattern_key: str,
    *,
    probe_spec_source: str | None = None,
    catalog_probe_category: str | None = None,
    pattern_mismatch: bool = False,
    extra_warnings: tuple[str, ...] = (),
) -> CollectPatternResult:
    meta = COLLECT_PATTERN_REGISTRY.get(pattern_key, COLLECT_PATTERN_REGISTRY["generic"])
    est = estimate_calls_for_pattern(pattern_key)
    return CollectPatternResult(
        pattern_key=pattern_key,
        mode=meta["mode"],
        label=meta["label"],
        api_calls_hint=meta["api_calls_hint"],
        probe_spec_source=probe_spec_source,
        catalog_probe_category=catalog_probe_category,
        pattern_mismatch=pattern_mismatch,
        warnings=extra_warnings,
        estimated_calls_per_year=est,
    )


def validate_collect_pattern(api_name: str) -> CollectPatternValidation:
    """Validate pattern consistency; return blocking errors for activation gate."""
    result = resolve_collect_pattern(api_name)
    blocking: list[str] = []

    catalog_mode = _mode_for_probe_category(result.catalog_probe_category)
    naive_would_fail = (
        catalog_mode
        and catalog_mode != result.mode
        and api_name not in API_PATTERN_OVERRIDES
    )

    if naive_would_fail:
        if catalog_mode == "trade_date" and result.mode == "exchange_date_range":
            blocking.append(
                f"{api_name}: catalog 标注 probe_category=trade_date，但探针参数为 "
                f"exchange+日期区间，必须使用 exchange_date_range（参考 trade_cal）。"
                f"请在 probe_templates.API_PROBE_OVERRIDES 登记或修正 catalog。"
            )
        elif result.estimated_calls_per_year and result.estimated_calls_per_year > 200:
            blocking.append(
                f"{api_name}: catalog probe_category={result.catalog_probe_category} "
                f"预估约 {result.estimated_calls_per_year} 次调用，超过默认预算 200；"
                f"推断模式应为 {result.pattern_key} (mode={result.mode})"
            )

    return CollectPatternValidation(result=result, blocking_errors=blocking)


def enrich_schema_collect(schema: dict[str, Any], api_name: str) -> dict[str, Any]:
    """Persist collect pattern into schema at L3 infer_schema."""
    validation = validate_collect_pattern(api_name)
    result = validation.result
    collect = dict(schema.get("collect") or {})
    collect.setdefault("max_codes_per_run", 50)
    collect.setdefault("max_api_calls_per_run", 200)
    collect["mode"] = result.mode
    collect["pattern"] = result.pattern_key
    schema["collect"] = collect
    schema["collect_pattern"] = {
        "pattern": result.pattern_key,
        "mode": result.mode,
        "label": result.label,
        "api_calls_hint": result.api_calls_hint,
        "probe_spec_source": result.probe_spec_source,
        "catalog_probe_category": result.catalog_probe_category,
        "pattern_mismatch": result.pattern_mismatch,
        "warnings": list(result.warnings),
        "estimated_calls_full_sync": result.estimated_calls_per_year,
        "example_apis": PATTERN_EXAMPLE_APIS.get(result.pattern_key, []),
    }
    return schema


def resolve_probe_params_for_api(api_name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Shared probe param resolution for collect strategies."""
    from app.catalog.tia_probe_registry import api_probe_meta, resolve_probe_params
    from app.services.tia.scan.probe_templates import API_PROBE_OVERRIDES, PROBE_TEMPLATES
    from app.sync.tia_collect.params import SNAPSHOT_FULL_MARKET_PARAMS, sanitize_collect_params

    if api_name in SNAPSHOT_FULL_MARKET_PARAMS:
        return dict(SNAPSHOT_FULL_MARKET_PARAMS[api_name])

    probe_params = dict(schema.get("probe_params") or {})
    if probe_params:
        return sanitize_collect_params(probe_params)

    meta = api_probe_meta(api_name) or {}
    raw = (meta.get("probe") or {}).get("params") or {}
    if raw:
        return sanitize_collect_params(resolve_probe_params(dict(raw)))

    tpl_key = API_PROBE_OVERRIDES.get(api_name)
    if tpl_key:
        tpl = PROBE_TEMPLATES.get(tpl_key) or {}
        raw = tpl.get("params") or {}
        if raw:
            return sanitize_collect_params(resolve_probe_params(dict(raw)))

    from app.services.tia.scan.probe_planner import resolve_probe_spec

    spec, _, _ = resolve_probe_spec(api_name)
    if spec:
        raw = spec.get("params") or {}
        if raw:
            return sanitize_collect_params(resolve_probe_params(dict(raw)))

    return {}


def discover_mislabeled_apis() -> list[dict[str, Any]]:
    """Scan catalog for probe_category vs param-shape mismatches (iter-10 audit)."""
    from app.services.tia.scan.tushare_doc_registry import load_api_by_doc_id

    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in load_api_by_doc_id().values():
        api_name = row.get("api")
        if not api_name or api_name in seen:
            continue
        seen.add(api_name)
        result = resolve_collect_pattern(api_name)
        if not result.pattern_mismatch:
            continue
        catalog_mode = _mode_for_probe_category(result.catalog_probe_category)
        findings.append(
            {
                "api_name": api_name,
                "catalog_probe_category": result.catalog_probe_category,
                "catalog_mode": catalog_mode,
                "inferred_pattern": result.pattern_key,
                "inferred_mode": result.mode,
                "probe_spec_source": result.probe_spec_source,
                "warnings": list(result.warnings),
                "has_override": api_name in API_PATTERN_OVERRIDES,
                "example_apis": PATTERN_EXAMPLE_APIS.get(result.pattern_key, []),
            }
        )
    return findings
