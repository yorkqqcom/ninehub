"""Collect params audit tests (iter-10 regression)."""

from app.services.tia.scan.tushare_doc_registry import resolve_api_meta
from app.sync.tia_collect.params import sanitize_collect_params
from app.services.tia.collect_pattern import resolve_probe_params_for_api


def test_resolve_api_meta_finds_daily_basic() -> None:
    meta = resolve_api_meta("daily_basic")
    assert meta is not None
    assert meta["probe_category"] == "ts_code_date_range"


def test_sanitize_collect_params_strips_probe_limit() -> None:
    assert sanitize_collect_params({"limit": 3, "exchange": ""}) == {"exchange": ""}


def test_stock_basic_collect_params_full_market() -> None:
    params = resolve_probe_params_for_api("stock_basic", {})
    assert params == {"exchange": "", "list_status": "L"}


def test_list_limit_snapshot_drops_probe_limit() -> None:
    params = resolve_probe_params_for_api("namechange", {})
    assert "limit" not in params


def test_daily_basic_not_sse_fallback() -> None:
    params = resolve_probe_params_for_api("daily_basic", {})
    assert params.get("exchange") != "SSE"
    assert "ts_code" in params or params == {}


def test_audit_stock_a_no_critical_sse_or_limit() -> None:
    from app.services.tia.collect_params_audit import run_audit

    result = run_audit("stock_a")
    critical = result["by_severity"]["critical"]
    bad = [
        f
        for f in critical
        if f["category"] in ("sse_fallback", "probe_limit_in_collect")
    ]
    assert bad == [], bad
