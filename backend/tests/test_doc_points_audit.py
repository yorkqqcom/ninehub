"""Tests for doc points coverage audit."""

from app.services.tia.scan.doc_points_audit import run_doc_points_coverage_audit
from app.services.tia.scan.tushare_doc_registry import resolve_canonical_api_meta
from scripts.validate_plain_doc_seeds import collect_seed_cache_mismatches


def test_daily_basic_and_suspend_d_use_distinct_doc_ids() -> None:
    daily = resolve_canonical_api_meta("daily_basic")
    suspend = resolve_canonical_api_meta("suspend_d")
    assert daily is not None and suspend is not None
    assert daily["doc_id"] == 32
    assert suspend["doc_id"] == 214
    assert daily["min_points"] == 2000
    assert suspend["min_points"] == 5000


def test_coverage_audit_no_missing_for_top_inst() -> None:
    report = run_doc_points_coverage_audit()
    missing_apis = {row["api"] for row in report.missing_min_points}
    assert "top_inst" not in missing_apis


def test_coverage_audit_report_shape() -> None:
    report = run_doc_points_coverage_audit()
    data = report.to_dict()
    assert "missing_min_points" in data
    assert "stale_doc_pages" in data
    assert "parse_gaps" in data
    assert "doc_id_multi_api" in data
    assert "sidebar_drift" in data
    assert "audit_summary" in data
    assert report.total_resolved_apis > 0


def test_doc_id_page_body_never_hosts_multiple_apis() -> None:
    """Iteration-200: document/2 page body has at most one 接口 line per doc_id."""
    report = run_doc_points_coverage_audit()
    assert report.audit_summary.page_body_multi_count == 0
    page_multi = [row for row in report.doc_id_multi_api if row["kind"] == "page_body_multi"]
    assert page_multi == []


def test_sidebar_drift_not_counted_as_blocking_multi_api() -> None:
    report = run_doc_points_coverage_audit()
    drift_kinds = {row["kind"] for row in report.sidebar_drift}
    blocking_kinds = {row["kind"] for row in report.doc_id_multi_api}
    assert drift_kinds <= {"page_vs_sidebar", "sidebar_multi"}
    assert blocking_kinds <= {"page_body_multi", "cache_api_mismatch"}
    assert report.audit_summary.sidebar_drift_count == len(report.sidebar_drift)


def test_plain_seeds_match_doc_pages_cache_api() -> None:
    """Phase C: compiled seeds must agree with cached page body api names."""
    assert collect_seed_cache_mismatches() == []


def test_parse_all_api_names_dedupes_repeated_lines() -> None:
    from app.services.tia.scan.tushare_doc_registry import parse_all_api_names_from_doc_text

    text = "接口：daily 描述：foo 接口：daily 描述：bar"
    assert parse_all_api_names_from_doc_text(text) == ["daily"]
