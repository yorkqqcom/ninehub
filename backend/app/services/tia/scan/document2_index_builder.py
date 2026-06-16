"""Build TIA official index from document/2 sidebar snapshot (single source of truth).

Design: docs/TIA_FULL_SCAN_REDESIGN.md — iterations 2–5.
"""

from __future__ import annotations

from pathlib import Path

from app.services.tia.scan.tushare_doc_registry import (
    get_api_canonical_doc_ids,
    build_doc_page_url,
    load_api_by_doc_id,
    load_doc_pages_cache,
    resolve_canonical_api_meta,
    resolve_sidebar_entry,
)
from app.services.tia.scan.tushare_sidebar_parser import parse_sidebar_markdown
from app.services.tia.scan.types import OfficialApiEntry, OfficialIndexSnapshot

_DEPRECATED_DOC_IDS = frozenset({35, 108})
_STOCK_A_CATEGORIES = frozenset({"股票数据"})
_CANONICAL_DOC_TO_API = {int(doc_id): api for api, doc_id in get_api_canonical_doc_ids().items()}


def resolve_sidebar_snapshot_path() -> Path | None:
    """Prefer MCP snapshot; fallback to fixtures markdown."""
    root = Path(__file__).resolve().parents[4]
    for candidate in (
        root / "scripts" / "mcp_document2_sidebar.snapshot.md",
        root / "scripts" / "fixtures" / "tushare_document2_sidebar.md",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_sidebar_links_from_snapshot() -> tuple[list[dict], Path | None]:
    path = resolve_sidebar_snapshot_path()
    if path is None:
        return [], None
    links = parse_sidebar_markdown(path.read_text(encoding="utf-8"))
    return links, path


def filter_links_by_scope(links: list[dict], index_scope: str) -> list[dict]:
    if index_scope != "stock_a":
        return links
    return [link for link in links if (link.get("category") or "") in _STOCK_A_CATEGORIES]


def resolve_sync_doc_ids_for_scan(index_scope: str = "stock_a") -> list[int]:
    """Doc ids for P0 doc-page sync — same snapshot scope as official index builder."""
    links, _ = load_sidebar_links_from_snapshot()
    scoped = filter_links_by_scope(links, index_scope)
    return sorted(
        {
            int(link["doc_id"])
            for link in scoped
            if link.get("doc_id") is not None and int(link["doc_id"]) not in _DEPRECATED_DOC_IDS
        }
    )


def build_document2_official_index(
    *,
    index_scope: str = "stock_a",
) -> OfficialIndexSnapshot:
    """Official scan index: snapshot menu links only (no registry supplement)."""
    links, _snapshot_path = load_sidebar_links_from_snapshot()
    scoped_links = filter_links_by_scope(links, index_scope)
    page_cache = load_doc_pages_cache()
    api_by_doc = load_api_by_doc_id()

    apis: list[OfficialApiEntry] = []
    seen_apis: set[str] = set()
    unresolved_doc_ids: list[int] = []
    doc_ids_traversed: list[int] = []

    for link in scoped_links:
        sidebar_doc_id = int(link["doc_id"])
        if sidebar_doc_id in _DEPRECATED_DOC_IDS:
            continue
        doc_ids_traversed.append(sidebar_doc_id)

        enriched = resolve_sidebar_entry(link, api_by_doc=api_by_doc, page_cache=page_cache)
        api_name = enriched.get("api")
        if not api_name and sidebar_doc_id in _CANONICAL_DOC_TO_API:
            api_name = _CANONICAL_DOC_TO_API[sidebar_doc_id]
        if not api_name:
            unresolved_doc_ids.append(sidebar_doc_id)
            continue
        api_name = str(api_name)
        canonical = resolve_canonical_api_meta(api_name) or {}
        doc_id = int(canonical["doc_id"]) if canonical.get("doc_id") is not None else sidebar_doc_id

        if api_name in seen_apis:
            continue
        seen_apis.add(api_name)

        min_points = canonical.get("min_points")
        if min_points is not None:
            min_points = int(min_points)

        apis.append(
            OfficialApiEntry(
                api=api_name,
                doc_id=doc_id,
                category=canonical.get("category") or enriched.get("category") or link.get("category"),
                label=canonical.get("label") or enriched.get("label") or link.get("label"),
                min_points=int(min_points) if min_points is not None else None,
                probe_category=canonical.get("probe_category") or enriched.get("probe_category"),
                doc_url=canonical.get("doc_url") or build_doc_page_url(doc_id),
            )
        )

    apis.sort(key=lambda e: (e.doc_id if e.doc_id is not None else 99999, e.api))
    return OfficialIndexSnapshot(
        provider="tushare",
        apis=apis,
        source="document2_sidebar_snapshot",
        version="2025-06-document2-snapshot",
        total=len(apis),
        scope=index_scope,
        sidebar_link_total=len(scoped_links),
        resolved_api_count=len(apis),
        unresolved_doc_ids=sorted(set(unresolved_doc_ids)),
        doc_ids_traversed=sorted(set(doc_ids_traversed)),
    )


def sidebar_index_metadata(snapshot: OfficialIndexSnapshot) -> dict:
    """Extra fields for scan job result_json.sidebar_index."""
    path = resolve_sidebar_snapshot_path()
    links, _ = load_sidebar_links_from_snapshot()
    return {
        "source": snapshot.source,
        "snapshot_path": str(path) if path else None,
        "snapshot_link_total": len(links),
        "scoped_link_total": snapshot.sidebar_link_total,
        "resolved_api_count": snapshot.resolved_api_count,
        "unresolved_doc_count": len(snapshot.unresolved_doc_ids),
        "doc_ids_traversed": len(snapshot.doc_ids_traversed),
    }
