"""Doc pages live sync service tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.tia.doc_pages_sync_service import (
    CACHE_PATH,
    DocPagesSyncService,
)
from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions


def _mock_fetch(doc_ids, **kwargs):
    pages = {}
    for doc_id in doc_ids:
        if doc_id == 26:
            pages[str(doc_id)] = {
                "api": "trade_cal",
                "min_points": 2000,
                "raw_text": "接口：trade_cal\n积分：需2000积分",
                "fetcher": "mock",
                "min_points_source": "doc_page_live",
            }
        elif doc_id == 28:
            pages[str(doc_id)] = {
                "api": "adj_factor",
                "min_points": 2000,
                "raw_text": "接口：adj_factor\n2000积分起",
                "fetcher": "mock",
                "min_points_source": "doc_page_live",
            }
    return pages


def test_doc_pages_sync_merge_and_dry_run() -> None:
    svc = DocPagesSyncService()
    opts = DocPagesSyncOptions(
        doc_ids=[26, 28],
        dry_run=True,
        rebuild_registry=False,
        patch_sidebar=False,
    )
    result = svc.run(None, opts, fetch_pages=_mock_fetch)
    assert result["dry_run"] is True
    assert result["merge_stats"]["with_points"] == 2
    assert result["merge_stats"]["with_api"] == 2


def test_doc_pages_sync_writes_cache_and_rebuilds_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.tia.doc_pages_sync_service as sync_mod

    cache_file = tmp_path / "cache.json"
    api_file = tmp_path / "api_by_doc.json"
    sidebar_file = tmp_path / "sidebar.json"
    sidebar_file.write_text(
        json.dumps(
            {
                "entries": [
                    {"doc_id": 26, "label": "trade_cal", "api": "trade_cal", "min_points": 120},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(sync_mod, "CACHE_PATH", cache_file)
    monkeypatch.setattr(sync_mod, "API_BY_DOC_PATH", api_file)
    monkeypatch.setattr(sync_mod, "SIDEBAR_PATH", sidebar_file)

    svc = DocPagesSyncService()
    opts = DocPagesSyncOptions(
        doc_ids=[26],
        rebuild_registry=True,
        patch_sidebar=True,
        reconcile_overrides=False,
    )
    result = svc.run(None, opts, fetch_pages=_mock_fetch)
    assert cache_file.is_file()
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["pages"]["26"]["min_points"] == 2000
    assert api_file.is_file()
    sidebar = json.loads(sidebar_file.read_text(encoding="utf-8"))
    assert sidebar["entries"][0]["min_points"] == 2000
    assert result["sidebar_patched"] == 1


def test_resolve_doc_ids_excludes_deprecated_108() -> None:
    svc = DocPagesSyncService()
    ids = svc.resolve_doc_ids(DocPagesSyncOptions(doc_ids=[26, 108, 28]))
    assert 108 not in ids
    assert 26 in ids and 28 in ids
