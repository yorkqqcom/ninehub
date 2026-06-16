"""Tushare official index from https://tushare.pro/document/2 (doc_id traversal)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.tia.scan.tushare_doc_registry import (
    load_doc_pages_cache,
    parse_api_name_from_doc_text,
    parse_min_points_from_doc_text,
    resolve_sidebar_entry,
)
from app.services.tia.scan.types import OfficialApiEntry, OfficialIndexSnapshot

_DEPRECATED_DOC_IDS = frozenset({35, 108})
_DOC14_CATALOG_PATH = (
    Path(__file__).resolve().parents[3] / "catalog" / "providers" / "tushare_doc14_catalog.json"
)
_DOCUMENT2_SIDEBAR_PATH = (
    Path(__file__).resolve().parents[3] / "catalog" / "providers" / "tushare_document2_sidebar.json"
)

STOCK_A_SIDEBAR_CATEGORIES = frozenset({"股票数据"})

STOCK_A_DOC14_CATEGORIES = frozenset(
    {
        "股票数据",
        "行情数据",
        "财务数据",
        "参考数据",
        "资金流向数据",
        "两融及转融通",
        "特色数据",
        "打板专题",
        "沪深港通",
        "概念板块",
        "其他",
    }
)


def load_document2_sidebar_raw() -> dict:
    if not _DOCUMENT2_SIDEBAR_PATH.is_file():
        return {"entries": [], "source_url": "https://tushare.pro/document/2"}
    return json.loads(_DOCUMENT2_SIDEBAR_PATH.read_text(encoding="utf-8"))


def load_doc14_catalog_raw() -> dict:
    if not _DOC14_CATALOG_PATH.is_file():
        return {"entries": [], "source_doc_id": 14}
    return json.loads(_DOC14_CATALOG_PATH.read_text(encoding="utf-8"))


def _filter_entries(entries: list[dict], index_scope: str, stock_cats: frozenset[str] | None) -> list[dict]:
    if index_scope != "stock_a" or not stock_cats:
        return entries
    return [e for e in entries if (e.get("category") or "") in stock_cats]


def _entry_to_official(enriched: dict) -> OfficialApiEntry | None:
    if not enriched.get("resolved") or not enriched.get("api"):
        return None
    api = str(enriched["api"])
    return OfficialApiEntry(
        api=api,
        doc_id=int(enriched["doc_id"]),
        category=enriched.get("category"),
        label=enriched.get("label"),
        min_points=int(enriched["min_points"]) if enriched.get("min_points") is not None else None,
        probe_category=enriched.get("probe_category") or "list_limit",
        doc_url=enriched.get("doc_url"),
    )


def _build_official_index(
    raw: dict,
    *,
    index_scope: str,
    source: str,
    stock_cats: frozenset[str] | None,
) -> OfficialIndexSnapshot:
    page_cache = load_doc_pages_cache()
    entries_raw = _filter_entries(raw.get("entries", []), index_scope, stock_cats)

    apis: list[OfficialApiEntry] = []
    seen_apis: set[str] = set()
    unresolved_doc_ids: list[int] = []
    doc_ids: list[int] = []

    for entry in entries_raw:
        doc_id = int(entry["doc_id"])
        if doc_id in _DEPRECATED_DOC_IDS:
            continue
        doc_ids.append(doc_id)
        enriched = entry if entry.get("resolved") is not None else resolve_sidebar_entry(entry, page_cache=page_cache)
        if not enriched.get("resolved"):
            unresolved_doc_ids.append(doc_id)
            continue
        official = _entry_to_official(enriched)
        if official is None or official.api in seen_apis:
            continue
        seen_apis.add(official.api)
        apis.append(official)

    apis.sort(key=lambda e: (e.doc_id or 0, e.api))
    return OfficialIndexSnapshot(
        provider="tushare",
        apis=apis,
        source=source,
        version=raw.get("version"),
        total=len(apis),
        scope=index_scope,
        sidebar_link_total=raw.get("sidebar_link_count", len(entries_raw)),
        resolved_api_count=len(apis),
        unresolved_doc_ids=sorted(unresolved_doc_ids),
        doc_ids_traversed=sorted(set(doc_ids)),
    )


def load_document2_sidebar_index(
    *,
    index_scope: str = "stock_a",
    stock_categories: frozenset[str] | None = None,
) -> OfficialIndexSnapshot:
    """document/2 左侧菜单：snapshot 遍历 + sidebar JSON 补全 API 解析。"""
    from app.services.tia.scan.document2_index_builder import build_document2_official_index

    snapshot = build_document2_official_index(index_scope=index_scope)
    raw = load_document2_sidebar_raw()
    stock_cats: frozenset[str] | None = None
    if index_scope == "stock_a":
        stock_cats = stock_categories or STOCK_A_SIDEBAR_CATEGORIES
    bundled = _build_official_index(
        raw,
        index_scope=index_scope,
        source="document2_sidebar_bundled",
        stock_cats=stock_cats,
    )

    if len(bundled.apis) > len(snapshot.apis):
        return bundled
    if snapshot.apis:
        return snapshot
    return bundled


def load_doc14_official_index(
    *,
    index_scope: str = "stock_a",
    stock_categories: frozenset[str] | None = None,
) -> OfficialIndexSnapshot:
    raw = load_doc14_catalog_raw()
    stock_cats: frozenset[str] | None = None
    if index_scope == "stock_a":
        stock_cats = stock_categories or STOCK_A_DOC14_CATEGORIES
    return _build_official_index(
        raw,
        index_scope=index_scope,
        source="doc14_catalog",
        stock_cats=stock_cats,
    )


def merge_entry(entry: dict, page_cache: dict[str, dict]) -> OfficialApiEntry | None:
    """Legacy helper for tests: enrich + convert to OfficialApiEntry."""
    doc_id = int(entry["doc_id"])
    if doc_id in _DEPRECATED_DOC_IDS:
        return None
    enriched = resolve_sidebar_entry(entry, page_cache=page_cache)
    if enriched.get("skipped") or not enriched.get("resolved"):
        return None
    return _entry_to_official(enriched)
