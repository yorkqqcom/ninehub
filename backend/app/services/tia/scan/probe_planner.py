"""Resolve probe specs and plan probe batches for full scan (doc_id traversal)."""

from __future__ import annotations

from typing import Any

from app.catalog.tia_probe_registry import api_probe_meta
from app.services.tia.scan.probe_templates import API_PROBE_OVERRIDES, PROBE_TEMPLATES
from app.services.tia.scan.types import OfficialApiEntry, ScanOptions
from app.services.tia.scan.api_spec_store import get_api_spec_by_name, get_api_spec


def resolve_probe_spec(
    api_name: str,
    official_entry: OfficialApiEntry | None = None,
) -> tuple[dict[str, Any] | None, str | None, int | None]:
    """Return (probe_spec, spec_source, min_points)."""
    override_key = API_PROBE_OVERRIDES.get(api_name)
    if override_key and override_key in PROBE_TEMPLATES:
        pts = official_entry.min_points if official_entry else None
        return PROBE_TEMPLATES[override_key], f"template:{override_key}", pts

    meta = api_probe_meta(api_name)
    if meta and meta.get("probe"):
        return meta["probe"], "explicit_probe", meta.get("min_points")

    doc_id = official_entry.doc_id if official_entry else None
    doc_row = None
    if doc_id is not None:
        doc_row = get_api_spec(doc_id)
    if doc_row is None:
        doc_row = get_api_spec_by_name(api_name)

    if doc_row and doc_row.get("sdk_valid") is False:
        doc_row = None

    if doc_row:
        from app.services.tia.scan.probe_spec_from_doc import (
            api_doc_spec_from_cache_row,
            build_probe_spec_from_doc,
        )

        ps = doc_row.get("probe_spec") or {}
        params = dict(ps.get("params") or {})
        expected = list(ps.get("expected_fields") or [])
        if not expected and doc_row.get("output_fields"):
            expected = list(doc_row["output_fields"])

        spec_model = api_doc_spec_from_cache_row(doc_row)
        if spec_model and (not expected or not params):
            built = build_probe_spec_from_doc(spec_model)
            if not expected:
                expected = list(built.get("expected_fields") or [])
            if not params:
                params = dict(built.get("params") or {})

        if expected or params:
            min_pts = doc_row.get("min_points")
            if official_entry and official_entry.min_points is not None:
                min_pts = official_entry.min_points
            return (
                {"params": params, "expected_fields": expected},
                "doc_spec_cache",
                int(min_pts) if min_pts is not None else None,
            )

    min_pts = official_entry.min_points if official_entry else None
    category = official_entry.probe_category if official_entry else None
    if category is None:
        from app.services.tia.scan.tushare_doc_registry import infer_probe_category, resolve_api_meta

        reg = resolve_api_meta(api_name)
        if reg:
            if reg.get("min_points") is not None:
                min_pts = int(reg["min_points"])
            category = infer_probe_category(
                category=reg.get("category"),
                subcategory=reg.get("subcategory"),
                explicit=reg.get("probe_category"),
            )

    if category and category in PROBE_TEMPLATES:
        spec = PROBE_TEMPLATES[category]
        from app.services.tia.collect_pattern import infer_collect_pattern

        inferred = infer_collect_pattern(
            spec.get("params") or {},
            expected_fields=spec.get("expected_fields"),
        )
        if inferred != category and inferred in PROBE_TEMPLATES:
            return PROBE_TEMPLATES[inferred], f"template:{inferred}", min_pts
        return spec, f"template:{category}", min_pts

    # fallback generic list probe for official-only APIs
    if official_entry:
        return PROBE_TEMPLATES.get("list_limit"), "template:list_limit", official_entry.min_points

    if category:
        return PROBE_TEMPLATES.get("list_limit"), "template:list_limit", min_pts

    return None, None, None


def plan_probe_apis(
    *,
    local_apis: list[str],
    new_on_official: list[str],
    unchanged: list[str],
    official_map: dict[str, OfficialApiEntry],
    options: ScanOptions,
    sdk_invalid_apis: set[str] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Pick APIs to live-probe under budget; traverse doc_id order when scope=all."""
    if not options.probe:
        return [], {"probe_enabled": False, "planned": 0, "skipped_no_spec": 0}

    invalid_sdk = sdk_invalid_apis or set()
    skipped_sdk_invalid: list[str] = []

    if options.probe_scope == "all":
        # doc_id ascending traversal
        candidates = []
        for e in sorted(
            official_map.values(),
            key=lambda x: (x.doc_id if x.doc_id is not None else 99999, x.api),
        ):
            if e.api in invalid_sdk:
                skipped_sdk_invalid.append(e.api)
            else:
                candidates.append(e.api)
    else:
        for api in sorted(set(local_apis) | set(new_on_official)):
            if api in invalid_sdk:
                skipped_sdk_invalid.append(api)
            else:
                candidates.append(api)

    with_spec: list[str] = []
    skipped_no_spec: list[str] = []
    for api in candidates:
        spec, _, _ = resolve_probe_spec(api, official_map.get(api))
        if spec:
            with_spec.append(api)
        else:
            skipped_no_spec.append(api)

    if options.probe_scope == "all":
        prioritized = with_spec
    else:
        new_set = set(new_on_official)
        local_only = set(local_apis) - set(unchanged) - new_set
        unchanged_set = set(unchanged)

        def sort_key(api: str) -> tuple[int, int, str]:
            entry = official_map.get(api)
            doc_ord = entry.doc_id if entry and entry.doc_id is not None else 99999
            if api in new_set:
                return (0, doc_ord, api)
            if api in local_only:
                return (1, doc_ord, api)
            if api in unchanged_set:
                return (2, doc_ord, api)
            return (3, doc_ord, api)

        prioritized = sorted(with_spec, key=sort_key)

    if options.probe_unlimited:
        limit = len(prioritized)
    else:
        limit = max(1, options.probe_limit) if options.probe_limit > 0 else len(prioritized)
    planned = prioritized[:limit]
    deferred = prioritized[limit:]

    meta = {
        "probe_enabled": True,
        "probe_scope": options.probe_scope,
        "probe_limit": options.probe_limit,
        "probe_unlimited": options.probe_unlimited,
        "planned": len(planned),
        "deferred": len(deferred),
        "skipped_no_spec": len(skipped_no_spec),
        "skipped_sdk_invalid": len(skipped_sdk_invalid),
        "candidate_total": len(candidates),
        "with_spec_total": len(with_spec),
        "deferred_apis": deferred[:30],
        "skipped_no_spec_sample": skipped_no_spec[:30],
        "skipped_sdk_invalid_sample": skipped_sdk_invalid[:30],
        "traversal": "doc_id_asc" if options.probe_scope == "all" else "priority",
    }
    return planned, meta
