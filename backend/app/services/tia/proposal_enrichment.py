"""Enrich TIA proposals with Tushare official doc metadata."""

from __future__ import annotations

from pathlib import Path

from app.catalog.registry import get_data_type_entry
from app.catalog.tia_probe_registry import OFFICIAL_ONLY_API_PROBES
from app.models.tia_proposal import TiaProposal
from app.services.tia.constants import api_to_label, resolve_catalog_data_types
from app.services.tia.scan.tushare_doc_catalog import load_document2_sidebar_raw
from app.services.tia.scan.tushare_doc_registry import (
    build_doc_page_url,
    resolve_canonical_api_meta,
)
from app.services.tia.scan.api_spec_store import build_api_spec_by_name_index, get_api_spec_by_name, get_api_spec

_PROVIDERS = Path(__file__).resolve().parents[2] / "catalog" / "providers"
_META_SOURCE_FILES = (
    _PROVIDERS / "tushare_api_specs_cache.json",
    _PROVIDERS / "tushare_document2_sidebar.json",
    _PROVIDERS / "tushare_doc_pages_cache.json",
)

_meta_map_cache: dict[str, dict] | None = None
_meta_map_mtime: float = 0.0


def _bundled_sources_mtime() -> float:
    mtimes = [0.0]
    for path in _META_SOURCE_FILES:
        try:
            if path.is_file():
                mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(mtimes)


def invalidate_api_meta_cache() -> None:
    global _meta_map_cache, _meta_map_mtime
    _meta_map_cache = None
    _meta_map_mtime = 0.0


def resolve_effective_min_points(
    api_name: str,
    api_meta: dict[str, dict],
    override_points: dict[str, int] | None = None,
    proposal_min_points_override: int | None = None,
) -> int | None:
    """manual proposal override > L1 tia_overrides > document/2 page cache."""
    if proposal_min_points_override is not None:
        return int(proposal_min_points_override)
    if override_points and api_name in override_points:
        return int(override_points[api_name])
    meta = api_meta.get(api_name, {})
    pts = meta.get("min_points")
    if pts is not None:
        return int(pts)
    return None


def resolve_doc_min_points(api_name: str, api_meta: dict[str, dict]) -> int | None:
    """Doc-page-only min_points (no manual / L1 override)."""
    meta = api_meta.get(api_name, {})
    pts = meta.get("min_points")
    if pts is not None:
        return int(pts)
    return None


def resolve_min_points_source(
    api_name: str,
    *,
    proposal_min_points_override: int | None = None,
    override_points: dict[str, int] | None = None,
    api_meta: dict[str, dict] | None = None,
) -> str | None:
    if proposal_min_points_override is not None:
        return "manual"
    if override_points and api_name in override_points:
        return "l1_override"
    meta_map = api_meta or {}
    if resolve_doc_min_points(api_name, meta_map) is not None:
        return "doc_page"
    return None


def apis_matching_points_filter(
    api_names: set[str],
    *,
    min_points_gte: int | None = None,
    min_points_lte: int | None = None,
    api_meta: dict[str, dict] | None = None,
    override_points: dict[str, int] | None = None,
    proposal_override_points: dict[str, int] | None = None,
) -> set[str]:
    """Return api_names whose effective min_points fall within [gte, lte]."""
    if min_points_gte is None and min_points_lte is None:
        return set()
    meta_map = api_meta or build_api_meta_map()
    proposal_overrides = proposal_override_points or {}
    matched: set[str] = set()
    for api in api_names:
        pts = resolve_effective_min_points(
            api,
            meta_map,
            override_points,
            proposal_min_points_override=proposal_overrides.get(api),
        )
        if pts is None:
            continue
        if min_points_gte is not None and pts < min_points_gte:
            continue
        if min_points_lte is not None and pts > min_points_lte:
            continue
        matched.add(api)
    return matched


def _sidebar_indexes() -> tuple[dict[str, dict], dict[int, dict]]:
    by_api: dict[str, dict] = {}
    by_doc: dict[int, dict] = {}
    for entry in load_document2_sidebar_raw().get("entries", []):
        api = entry.get("api")
        doc_id = entry.get("doc_id")
        if api:
            by_api[str(api)] = entry
        if doc_id is not None:
            by_doc[int(doc_id)] = entry
    return by_api, by_doc


def verify_api_doc_link(
    api_name: str,
    *,
    candidate_doc_id: int | None = None,
) -> dict:
    """Verify api_name matches wctapi page at doc_id; only then return doc link."""
    api_key = api_name.strip().lower()
    spec = get_api_spec_by_name(api_key)
    if spec and str(spec.get("api", "")).lower() == api_key:
        doc_id = int(spec["doc_id"])
        return {
            "status": "ok",
            "api": api_name,
            "doc_id": doc_id,
            "doc_url": build_doc_page_url(doc_id),
            "page_api": spec.get("api"),
            "message": None,
        }

    check_doc_id = candidate_doc_id
    if check_doc_id is None and spec:
        check_doc_id = spec.get("doc_id")

    if check_doc_id is not None:
        page = get_api_spec(int(check_doc_id))
        page_api = str(page.get("api", "")).lower() if page and page.get("api") else None
        if page_api == api_key:
            doc_id = int(check_doc_id)
            return {
                "status": "ok",
                "api": api_name,
                "doc_id": doc_id,
                "doc_url": build_doc_page_url(doc_id),
                "page_api": page.get("api") if page else api_name,
                "message": None,
            }
        if page_api:
            return {
                "status": "doc_mismatch",
                "api": api_name,
                "doc_id": int(check_doc_id),
                "doc_url": build_doc_page_url(int(check_doc_id)),
                "page_api": page.get("api") if page else None,
                "message": (
                    f"doc_id={check_doc_id} 页面接口为 {page.get('api')}，"
                    f"与提案 api_name={api_name} 不一致"
                ),
            }

    return {
        "status": "no_spec",
        "api": api_name,
        "doc_id": None,
        "doc_url": None,
        "page_api": None,
        "message": f"wctapi 未找到接口 {api_name} 的文档页",
    }


def build_api_meta_map(*, force: bool = False) -> dict[str, dict]:
    """api_name -> metadata; doc_url only when wctapi page api matches."""
    global _meta_map_cache, _meta_map_mtime
    mtime = _bundled_sources_mtime()
    if not force and _meta_map_cache is not None and mtime == _meta_map_mtime:
        return _meta_map_cache

    specs_by_api = build_api_spec_by_name_index()
    sidebar_by_api, sidebar_by_doc = _sidebar_indexes()

    out: dict[str, dict] = {}
    for api, meta in OFFICIAL_ONLY_API_PROBES.items():
        out[api] = {
            "doc_id": meta.get("doc_id"),
            "min_points": meta.get("min_points"),
            "label": api_to_label(api),
            "source": "official_only",
        }

    all_apis = sorted(set(specs_by_api) | set(sidebar_by_api) | set(out))
    for api in all_apis:
        spec = specs_by_api.get(api)
        sidebar = sidebar_by_api.get(api) or {}
        prev = out.get(api, {})
        verified = verify_api_doc_link(api)

        min_points = None
        min_points_source = None
        if spec and spec.get("min_points") is not None:
            min_points = int(spec["min_points"])
            min_points_source = spec.get("min_points_source") or "wctapi_md"
        elif prev.get("min_points") is not None:
            min_points = prev.get("min_points")
            min_points_source = prev.get("min_points_source")

        doc_id = verified.get("doc_id") if verified["status"] == "ok" else None
        doc_url = verified.get("doc_url") if verified["status"] == "ok" else None
        if doc_id is None and sidebar.get("doc_id") and not spec:
            sid = int(sidebar["doc_id"])
            retry = verify_api_doc_link(api, candidate_doc_id=sid)
            if retry["status"] == "ok":
                doc_id = retry.get("doc_id")
                doc_url = retry.get("doc_url")

        out[api] = {
            "doc_id": doc_id,
            "min_points": min_points,
            "min_points_source": min_points_source,
            "label": sidebar.get("label") or prev.get("label") or api_to_label(api),
            "category": sidebar.get("category") or prev.get("category"),
            "source": "wctapi_md" if spec else (prev.get("source") or "sidebar"),
            "doc_url": doc_url,
            "doc_link_status": verified["status"],
        }

    _meta_map_cache = out
    _meta_map_mtime = mtime
    return out


def _spec_summary(spec: dict) -> dict:
    return {
        "description": spec.get("description"),
        "input_params": spec.get("input_params") or [],
        "output_params": spec.get("output_params") or [],
        "output_fields": spec.get("output_fields") or [],
        "sample_codes": (spec.get("sample_codes") or [])[:3],
        "sdk_valid": spec.get("sdk_valid"),
        "spec_source": spec.get("spec_source") or spec.get("fetcher"),
    }


def _resolve_meta_for_api(
    api_name: str,
    meta_map: dict[str, dict],
) -> dict:
    meta = dict(meta_map.get(api_name) or {})
    verified = verify_api_doc_link(
        api_name,
        candidate_doc_id=meta.get("doc_id"),
    )
    if verified["status"] == "ok":
        meta["doc_id"] = verified.get("doc_id")
        meta["doc_url"] = verified.get("doc_url")
        meta["doc_link_status"] = "ok"
        return meta

    canonical = resolve_canonical_api_meta(api_name) or {}
    retry = verify_api_doc_link(
        api_name,
        candidate_doc_id=canonical.get("doc_id"),
    )
    merged = {**meta, **canonical}
    if retry["status"] == "ok":
        merged["doc_id"] = retry.get("doc_id")
        merged["doc_url"] = retry.get("doc_url")
        merged["doc_link_status"] = "ok"
    else:
        merged["doc_id"] = None
        merged["doc_url"] = None
        merged["doc_link_status"] = retry["status"]
        merged["doc_link_message"] = retry.get("message")
        if retry.get("page_api"):
            merged["doc_page_api"] = retry.get("page_api")
    return merged


def enrich_proposal(
    proposal: TiaProposal,
    api_meta: dict[str, dict] | None = None,
    override_points: dict[str, int] | None = None,
    *,
    include_spec: bool = False,
) -> dict:
    """Return dict fields to merge into TiaProposalResponse."""
    meta_map = api_meta or build_api_meta_map()
    meta = _resolve_meta_for_api(proposal.api_name, meta_map)
    doc_id = meta.get("doc_id")
    doc_url = meta.get("doc_url")
    entry = None
    if proposal.data_type:
        for dt in resolve_catalog_data_types(proposal.data_type, proposal.api_name):
            entry = get_data_type_entry(dt)
            if entry:
                break

    result = {
        "doc_id": doc_id,
        "doc_url": doc_url,
        "min_points": resolve_effective_min_points(
            proposal.api_name,
            meta_map,
            override_points,
            proposal_min_points_override=proposal.min_points_override,
        ),
        "min_points_doc": resolve_doc_min_points(proposal.api_name, meta_map),
        "min_points_override": proposal.min_points_override,
        "min_points_source": resolve_min_points_source(
            proposal.api_name,
            proposal_min_points_override=proposal.min_points_override,
            override_points=override_points,
            api_meta=meta_map,
        ),
        "label": meta.get("label") or api_to_label(proposal.api_name),
        "category": meta.get("category"),
        "browse_enabled": entry.browse_enabled if entry else False,
    }

    if not include_spec:
        return result

    spec = get_api_spec_by_name(proposal.api_name)
    spec_summary = _spec_summary(spec) if spec else None
    result.update(
        {
            "description": (spec_summary or {}).get("description"),
            "input_params": (spec_summary or {}).get("input_params") or [],
            "output_fields": (spec_summary or {}).get("output_fields") or [],
            "output_params": (spec_summary or {}).get("output_params") or [],
            "sample_codes": (spec_summary or {}).get("sample_codes") or [],
            "sdk_valid": (spec_summary or {}).get("sdk_valid"),
            "spec_source": (spec_summary or {}).get("spec_source"),
        }
    )
    return result
