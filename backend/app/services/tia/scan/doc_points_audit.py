"""Audit Tushare document/2 min_points coverage (iteration-20 layered diagnostic).

Phase A — severity tiers for doc_id / api binding:
  P0 page_body_multi     — one doc_id, multiple 接口 lines (would challenge 1:1 model)
  P1 cache_api_mismatch  — cache.api ≠ page body (blocking until cache refresh)
  P2 page_vs_sidebar     — sidebar label drift (informational; page body wins)
  P2 sidebar_multi       — multiple sidebar apis on one doc_id (informational)

``has_issues`` counts P0+P1 multi-api rows only; P2 rows live in ``sidebar_drift``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.services.tia.scan.doc_points_resolver import (
    audit_bundled_vs_doc_page,
    is_stale_doc_page_entry,
    parse_min_points_from_cache_entry,
    resolve_min_points_from_doc_page,
)
from app.services.tia.scan.tushare_doc_catalog import load_document2_sidebar_raw
from app.services.tia.scan.tushare_doc_registry import (
    _DOC_ID_OVERRIDES,
    _load_json,
    build_api_by_doc_id,
    build_doc_page_url,
    load_doc_pages_cache,
    parse_all_api_names_from_doc_text,
    resolve_canonical_api_meta,
)

Severity = Literal["P0", "P1", "P2"]
_MULTI_API_BLOCKING_KINDS = frozenset({"page_body_multi", "cache_api_mismatch"})
_SIDEBAR_DRIFT_KINDS = frozenset({"page_vs_sidebar", "sidebar_multi"})

_KIND_SEVERITY: dict[str, Severity] = {
    "page_body_multi": "P0",
    "cache_api_mismatch": "P1",
    "page_vs_sidebar": "P2",
    "sidebar_multi": "P2",
}


def _raw_bundled_min_points_map() -> dict[int, int | None]:
    """Bundled JSON min_points hints before doc-page overlay (audit only)."""
    by_doc: dict[int, int | None] = {}
    for name in (
        "tushare_stock_official_apis.json",
        "tushare_official_apis.json",
        "tushare_doc14_catalog.json",
        "tushare_document2_sidebar.json",
    ):
        key = "apis" if name.startswith("tushare_stock") or name == "tushare_official_apis.json" else "entries"
        for item in _load_json(name).get(key, []):
            doc_id = item.get("doc_id")
            if doc_id is None:
                continue
            pts = item.get("min_points")
            if pts is not None:
                by_doc[int(doc_id)] = int(pts)
    return by_doc


@dataclass
class DocPointsAuditSummary:
    """Aggregated counts for coverage dashboard (iteration-20)."""

    page_body_multi_count: int = 0
    blocking_multi_api_count: int = 0
    sidebar_drift_count: int = 0
    cache_api_mismatch_count: int = 0


@dataclass
class DocPointsCoverageReport:
    """Result of a full min_points coverage audit."""

    total_resolved_apis: int = 0
    missing_min_points: list[dict[str, Any]] = field(default_factory=list)
    stale_doc_pages: list[dict[str, Any]] = field(default_factory=list)
    parse_gaps: list[dict[str, Any]] = field(default_factory=list)
    bundled_mismatches: list[dict[str, Any]] = field(default_factory=list)
    doc_id_conflicts: list[dict[str, Any]] = field(default_factory=list)
    doc_id_multi_api: list[dict[str, Any]] = field(default_factory=list)
    sidebar_drift: list[dict[str, Any]] = field(default_factory=list)
    audit_summary: DocPointsAuditSummary = field(default_factory=DocPointsAuditSummary)
    override_doc_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @property
    def has_issues(self) -> bool:
        return bool(
            self.missing_min_points
            or self.stale_doc_pages
            or self.parse_gaps
            or self.bundled_mismatches
            or self.doc_id_conflicts
            or self.doc_id_multi_api
        )


def _annotate_issue(row: dict[str, Any]) -> dict[str, Any]:
    kind = str(row.get("kind", ""))
    return {**row, "severity": _KIND_SEVERITY.get(kind, "P2")}


def _split_doc_id_binding_issues(
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], DocPointsAuditSummary]:
    """Partition multi-api / drift rows and build summary counts."""
    blocking: list[dict[str, Any]] = []
    drift: list[dict[str, Any]] = []
    summary = DocPointsAuditSummary()

    for raw in issues:
        row = _annotate_issue(raw)
        kind = row["kind"]
        if kind in _MULTI_API_BLOCKING_KINDS:
            blocking.append(row)
            if kind == "page_body_multi":
                summary.page_body_multi_count += 1
            if kind == "cache_api_mismatch":
                summary.cache_api_mismatch_count += 1
        elif kind in _SIDEBAR_DRIFT_KINDS:
            drift.append(row)
            summary.sidebar_drift_count += 1

    summary.blocking_multi_api_count = len(blocking)
    return blocking, drift, summary


def _collect_doc_id_binding_issues(
    *,
    page_cache: dict[str, dict],
    sidebar_entries: list[dict],
) -> list[dict[str, Any]]:
    """Collect doc_id binding anomalies (page body is authoritative)."""
    issues: list[dict[str, Any]] = []
    sidebar_by_doc: dict[int, list[str]] = {}
    for entry in sidebar_entries:
        if not entry.get("api"):
            continue
        doc_id = int(entry["doc_id"])
        api = str(entry["api"]).lower()
        if api not in sidebar_by_doc.setdefault(doc_id, []):
            sidebar_by_doc[doc_id].append(api)

    seen_doc_ids: set[int] = set(sidebar_by_doc.keys()) | {int(k) for k in page_cache}
    for doc_id in sorted(seen_doc_ids):
        cached = page_cache.get(str(doc_id), {})
        raw_text = cached.get("raw_text") or ""
        page_apis = parse_all_api_names_from_doc_text(raw_text)
        if len(page_apis) > 1:
            issues.append(
                {
                    "kind": "page_body_multi",
                    "doc_id": doc_id,
                    "apis": page_apis,
                    "doc_url": build_doc_page_url(doc_id),
                }
            )
            continue

        page_api = page_apis[0] if page_apis else None
        if page_api is None:
            continue

        cached_api = str(cached.get("api") or "").lower() or None
        if cached_api and cached_api != page_api:
            issues.append(
                {
                    "kind": "cache_api_mismatch",
                    "doc_id": doc_id,
                    "page_api": page_api,
                    "cached_api": cached_api,
                    "doc_url": build_doc_page_url(doc_id),
                }
            )

        sidebar_apis = sidebar_by_doc.get(doc_id, [])
        if len(sidebar_apis) > 1:
            issues.append(
                {
                    "kind": "sidebar_multi",
                    "doc_id": doc_id,
                    "page_api": page_api,
                    "sidebar_apis": sidebar_apis,
                    "doc_url": build_doc_page_url(doc_id),
                }
            )
        elif len(sidebar_apis) == 1 and sidebar_apis[0] != page_api:
            issues.append(
                {
                    "kind": "page_vs_sidebar",
                    "doc_id": doc_id,
                    "page_api": page_api,
                    "sidebar_api": sidebar_apis[0],
                    "doc_url": build_doc_page_url(doc_id),
                }
            )

    return issues


def _collect_doc_id_conflicts(by_doc: dict[int, dict]) -> list[dict[str, Any]]:
    api_docs: dict[str, list[int]] = {}
    for doc_id, row in by_doc.items():
        api = row.get("api")
        if not api:
            continue
        api_docs.setdefault(str(api), []).append(int(doc_id))

    conflicts: list[dict[str, Any]] = []
    for api, doc_ids in sorted(api_docs.items()):
        if len(doc_ids) < 2:
            continue
        canonical = resolve_canonical_api_meta(api)
        conflicts.append(
            {
                "api": api,
                "doc_ids": sorted(doc_ids),
                "canonical_doc_id": canonical.get("doc_id") if canonical else None,
            }
        )
    return conflicts


def run_doc_points_coverage_audit(
    *,
    page_cache: dict[str, dict] | None = None,
    sidebar_entries: list[dict] | None = None,
) -> DocPointsCoverageReport:
    """Scan resolved sidebar APIs for min_points gaps."""
    cache = page_cache if page_cache is not None else load_doc_pages_cache()
    by_doc = build_api_by_doc_id()
    raw_bundled = _raw_bundled_min_points_map()
    entries = sidebar_entries or load_document2_sidebar_raw().get("entries", [])
    resolved = [e for e in entries if e.get("resolved") and e.get("api")]

    report = DocPointsCoverageReport(
        total_resolved_apis=len(resolved),
        override_doc_ids=sorted(_DOC_ID_OVERRIDES.keys()),
    )

    for entry in resolved:
        api = str(entry["api"])
        doc_id = int(entry["doc_id"])
        doc_key = str(doc_id)
        cached = cache.get(doc_key, {})
        canonical = resolve_canonical_api_meta(api) or {}
        effective_pts = canonical.get("min_points")
        doc_pts, _doc_source = resolve_min_points_from_doc_page(doc_id, page_cache=cache)

        if effective_pts is None:
            report.missing_min_points.append(
                {
                    "api": api,
                    "doc_id": doc_id,
                    "cache_source": cached.get("source"),
                    "has_raw_text": bool(cached.get("raw_text")),
                    "doc_url": build_doc_page_url(doc_id),
                }
            )

        if is_stale_doc_page_entry(cached):
            report.stale_doc_pages.append(
                {
                    "api": api,
                    "doc_id": doc_id,
                    "cache_source": cached.get("source"),
                    "fetcher": cached.get("fetcher"),
                }
            )

        raw_text = cached.get("raw_text") or ""
        if raw_text:
            parsed, _ = parse_min_points_from_cache_entry(cached)
            if parsed is None and re.search(r"\d+\s*积分", raw_text):
                report.parse_gaps.append(
                    {
                        "api": api,
                        "doc_id": doc_id,
                        "raw_text_preview": raw_text[:120],
                    }
                )

        bundled_pts = raw_bundled.get(doc_id)
        if bundled_pts is None:
            bundled_pts = by_doc.get(doc_id, {}).get("min_points")
        mismatch = audit_bundled_vs_doc_page(doc_id, bundled_pts, page_cache=cache)
        if mismatch:
            mismatch["api"] = api
            report.bundled_mismatches.append(mismatch)

        if canonical.get("doc_id") is not None and int(canonical["doc_id"]) != doc_id:
            report.doc_id_conflicts.append(
                {
                    "kind": "sidebar_vs_canonical",
                    "api": api,
                    "sidebar_doc_id": doc_id,
                    "canonical_doc_id": int(canonical["doc_id"]),
                    "sidebar_pts": doc_pts,
                    "canonical_pts": effective_pts,
                }
            )

    for row in _collect_doc_id_conflicts(by_doc):
        row["kind"] = "multi_doc_id"
        report.doc_id_conflicts.append(row)

    binding_issues = _collect_doc_id_binding_issues(page_cache=cache, sidebar_entries=entries)
    blocking, drift, summary = _split_doc_id_binding_issues(binding_issues)
    report.doc_id_multi_api = blocking
    report.sidebar_drift = drift
    report.audit_summary = summary

    return report
