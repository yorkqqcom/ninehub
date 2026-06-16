"""Tests for full-scan points re-identification (50-iteration design)."""

from app.services.tia.scan.document2_index_builder import (
    build_document2_official_index,
    resolve_sync_doc_ids_for_scan,
)
from app.services.tia.scan.scan_points_coverage import build_scan_points_coverage
from app.services.tia.scan.types import ScanOptions


def test_resolve_sync_doc_ids_stock_a_matches_snapshot_scope() -> None:
    doc_ids = resolve_sync_doc_ids_for_scan("stock_a")
    snap = build_document2_official_index(index_scope="stock_a")
    assert len(doc_ids) >= 90
    assert set(snap.doc_ids_traversed).issubset(set(doc_ids))


def test_resolve_sync_doc_ids_mixed_is_broader_or_equal() -> None:
    stock = resolve_sync_doc_ids_for_scan("stock_a")
    mixed = resolve_sync_doc_ids_for_scan("mixed")
    assert len(mixed) >= len(stock)


def test_scan_options_full_defaults_sync_doc_specs() -> None:
    opts = ScanOptions.from_dict({"mode": "full", "provider": "tushare"})
    assert opts.sync_doc_specs is True
    assert opts.sync_doc_pages is False


def test_scan_options_catalog_defaults_no_sync_doc_pages() -> None:
    opts = ScanOptions.from_dict({"mode": "catalog", "provider": "tushare"})
    assert opts.sync_doc_pages is False


def test_build_scan_points_coverage_includes_api_live() -> None:
    snap = build_document2_official_index(index_scope="stock_a")
    probes = [
        {
            "api": "income",
            "status": "failed_points",
            "api_live_min_points": 2000,
            "interface_level": 2000,
            "catalog_min_points": 120,
            "points_doc_mismatch": True,
        }
    ]
    cov = build_scan_points_coverage(snap, sync_doc_pages=False, api_probes=probes)
    assert cov["points_mode"] == "api_live"
    assert cov["api_live_with_min_points"] == 1
    assert cov["api_live_points_mismatch"] == 1
    assert cov["api_live_min_points_sample"][0]["api"] == "income"


def test_build_scan_points_coverage_shape() -> None:
    snap = build_document2_official_index(index_scope="stock_a")
    cov = build_scan_points_coverage(snap, sync_doc_pages=True, doc_pages_sync={"skipped": True})
    assert "index_apis_total" in cov
    assert cov["index_apis_total"] == len(snap.apis)
    assert "index_apis_with_min_points" in cov
    assert cov["sync_doc_pages"] is True
    assert cov["doc_pages_sync"]["skipped"] is True
