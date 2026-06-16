"""Resolve api ↔ doc_id ↔ min_points from document/2 page body (5-iteration design).

Iteration 1 — Page body ``接口：{api}`` is authoritative for api name on a doc_id.
Iteration 2 — ``_API_CANONICAL_DOC_IDS`` fixes known sidebar doc_id drift.
Iteration 3 — min_points always re-parsed from ``raw_text`` (never stale cache alone).
Iteration 4 — Mismatch guard: if page api ≠ requested api, do not return that page's points.
Iteration 5 — Sidebar patch + api→doc map rebuilt from cache after bootstrap.
"""

from __future__ import annotations

from app.services.tia.scan.doc_points_resolver import parse_min_points_from_cache_entry
from app.services.tia.scan.min_points_extractor import extract_access_min_points
from app.services.tia.scan.tushare_doc_registry import (
    get_api_canonical_doc_ids,
    load_doc_pages_cache,
    parse_api_name_from_doc_text,
)


def parse_api_from_page_entry(entry: dict) -> str | None:
    raw_text = entry.get("raw_text") or ""
    api = entry.get("api")
    parsed = parse_api_name_from_doc_text(raw_text)
    if parsed:
        return parsed
    return str(api).lower() if api else None


def build_page_api_doc_map(page_cache: dict[str, dict] | None = None) -> dict[str, int]:
    """Map api_name → doc_id using wctapi specs, page body, and canonical overrides."""
    from app.services.tia.scan.api_spec_store import build_api_to_doc_id_map

    mapping = build_api_to_doc_id_map()
    cache = page_cache if page_cache is not None else load_doc_pages_cache()
    for doc_key, entry in cache.items():
        if entry.get("error"):
            continue
        api = parse_api_from_page_entry(entry)
        if not api:
            continue
        doc_id = int(doc_key)
        if api not in mapping:
            mapping[api] = doc_id
    for api, doc_id in get_api_canonical_doc_ids().items():
        mapping[api] = int(doc_id)
    return mapping


def resolve_doc_id_for_api(
    api_name: str,
    *,
    page_cache: dict[str, dict] | None = None,
) -> int | None:
    """Return document/2 doc_id whose wctapi page matches ``api_name``."""
    api_name = api_name.strip().lower()
    canonical = get_api_canonical_doc_ids()
    if api_name in canonical:
        return int(canonical[api_name])

    from app.services.tia.scan.api_spec_store import get_api_spec_by_name

    spec = get_api_spec_by_name(api_name)
    if spec and spec.get("doc_id") is not None:
        return int(spec["doc_id"])

    cache = page_cache if page_cache is not None else load_doc_pages_cache()
    for doc_key, entry in cache.items():
        if parse_api_from_page_entry(entry) == api_name:
            return int(doc_key)

    return build_page_api_doc_map(cache).get(api_name)


def resolve_min_points_for_api(
    api_name: str,
    *,
    page_cache: dict[str, dict] | None = None,
) -> tuple[int | None, str]:
    """Resolve access min_points for ``api_name`` via wctapi spec or document/2 page."""
    from app.services.tia.scan.api_spec_store import get_api_spec_by_name

    spec = get_api_spec_by_name(api_name)
    if spec and spec.get("min_points") is not None:
        return int(spec["min_points"]), str(spec.get("min_points_source") or "wctapi_md")

    cache = page_cache if page_cache is not None else load_doc_pages_cache()
    doc_id = resolve_doc_id_for_api(api_name, page_cache=cache)
    if doc_id is None:
        return None, "unknown"

    entry = cache.get(str(doc_id), {})
    if not entry:
        return None, "unknown"

    page_api = parse_api_from_page_entry(entry)
    if page_api and page_api != api_name:
        return None, "api_doc_mismatch"

    raw_text = entry.get("raw_text") or ""
    if raw_text:
        pts = extract_access_min_points(raw_text)
        if pts is not None:
            source = str(entry.get("min_points_source") or "doc_page_parsed")
            return int(pts), source
        if "积分消耗" in raw_text:
            return None, "consumption_only"

    pts, source = parse_min_points_from_cache_entry(entry)
    if pts is not None:
        return int(pts), source
    return None, str(entry.get("min_points_source") or "unknown")


def validate_api_points_binding(
    api_name: str,
    *,
    page_cache: dict[str, dict] | None = None,
) -> dict:
    """Audit row for one api (used by scripts/tests)."""
    cache = page_cache if page_cache is not None else load_doc_pages_cache()
    doc_id = resolve_doc_id_for_api(api_name, page_cache=cache)
    entry = cache.get(str(doc_id), {}) if doc_id is not None else {}
    pts, source = resolve_min_points_for_api(api_name, page_cache=cache)
    return {
        "api": api_name,
        "doc_id": doc_id,
        "page_api": parse_api_from_page_entry(entry) if entry else None,
        "min_points": pts,
        "min_points_source": source,
        "raw_text_preview": (entry.get("raw_text") or "")[:120],
    }
