"""Points re-identification coverage summary for TIA full scan."""

from __future__ import annotations

from typing import Any

from app.services.tia.scan.tushare_doc_registry import load_doc_pages_cache
from app.services.tia.scan.types import OfficialIndexSnapshot


def build_scan_points_coverage(
    official_snapshot: OfficialIndexSnapshot,
    *,
    sync_doc_pages: bool = False,
    doc_pages_sync: dict[str, Any] | None = None,
    page_cache: dict[str, dict] | None = None,
    api_probes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize min_points state: doc cache + index + API-live probes (iteration-200)."""
    cache = page_cache if page_cache is not None else load_doc_pages_cache()

    with_raw_text = 0
    with_min_points_cached = 0
    for entry in cache.values():
        if entry.get("raw_text"):
            with_raw_text += 1
        if entry.get("min_points") is not None:
            with_min_points_cached += 1

    index_with_pts = 0
    missing_samples: list[dict[str, Any]] = []
    for entry in official_snapshot.apis:
        if entry.min_points is not None:
            index_with_pts += 1
        elif len(missing_samples) < 20:
            missing_samples.append(
                {
                    "api": entry.api,
                    "doc_id": entry.doc_id,
                    "label": entry.label,
                }
            )

    probes = api_probes or []
    api_live_with_pts = sum(1 for p in probes if p.get("api_live_min_points") is not None)
    api_live_permission_errors = sum(
        1 for p in probes if p.get("status") == "failed_points"
    )
    api_live_mismatch = sum(1 for p in probes if p.get("points_doc_mismatch"))
    api_live_samples = [
        {
            "api": p.get("api"),
            "api_live_min_points": p.get("api_live_min_points"),
            "interface_level": p.get("interface_level"),
            "catalog_min_points": p.get("catalog_min_points"),
            "official_doc_min_points": p.get("official_doc_min_points"),
        }
        for p in probes
        if p.get("api_live_min_points") is not None
    ][:20]

    total_apis = len(official_snapshot.apis)
    sync_meta = doc_pages_sync or {}

    return {
        "points_mode": "api_live" if probes else "doc_cache",
        "sync_doc_pages": sync_doc_pages,
        "page_cache_total": len(cache),
        "page_cache_with_raw_text": with_raw_text,
        "page_cache_with_min_points": with_min_points_cached,
        "index_apis_total": total_apis,
        "index_apis_with_min_points": index_with_pts,
        "index_apis_missing_min_points": total_apis - index_with_pts,
        "missing_min_points_sample": missing_samples,
        "api_probe_total": len(probes),
        "api_live_with_min_points": api_live_with_pts,
        "api_live_permission_errors": api_live_permission_errors,
        "api_live_points_mismatch": api_live_mismatch,
        "api_live_min_points_sample": api_live_samples,
        "doc_pages_sync": {
            "skipped": sync_meta.get("skipped"),
            "reason": sync_meta.get("reason"),
            "stale_count": sync_meta.get("stale_count"),
            "merge_stats": sync_meta.get("merge_stats"),
        }
        if sync_meta
        else None,
    }
