"""Tests for document/2 sidebar snapshot index builder."""

from app.services.tia.scan.document2_index_builder import (
    build_document2_official_index,
    load_sidebar_links_from_snapshot,
    resolve_sidebar_snapshot_path,
)
from app.services.tia.scan.tushare_doc_registry import load_official_snapshot_doc_ids


def test_snapshot_path_exists() -> None:
    assert resolve_sidebar_snapshot_path() is not None


def test_load_sidebar_links_from_snapshot() -> None:
    links, path = load_sidebar_links_from_snapshot()
    assert path is not None
    assert len(links) >= 100
    assert all("doc_id" in link for link in links)


def test_build_index_stock_a_from_snapshot_only() -> None:
    snap = build_document2_official_index(index_scope="stock_a")
    assert snap.source == "document2_sidebar_snapshot"
    assert snap.total >= 45
    official_ids = load_official_snapshot_doc_ids()
    for entry in snap.apis:
        assert entry.doc_id is not None
        assert entry.doc_url and f"doc_id={entry.doc_id}" in entry.doc_url
        assert int(entry.doc_id) in official_ids


def test_canonical_doc_ids_in_stock_a_index() -> None:
    snap = build_document2_official_index(index_scope="stock_a")
    by_api = snap.as_map()
    assert by_api["top10_holders"].doc_id == 61
    assert by_api["report_rc"].doc_id == 292
    assert by_api["daily_basic"].doc_id == 32
