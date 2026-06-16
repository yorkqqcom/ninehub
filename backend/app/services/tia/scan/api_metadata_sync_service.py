"""Sync Tushare API metadata: wctapi markdown crawl + optional SDK validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.services.tia.doc_pages_sync_service import DocPagesSyncService
from app.services.tia.scan.api_spec_store import (
    build_api_to_doc_id_map,
    load_api_specs_cache,
    spec_to_page_cache_entry,
)
from app.services.tia.scan.api_spec_sync_service import ApiSpecSyncService
from app.services.tia.default_proposal_seed import write_default_proposals_file

ProgressFn = Callable[[int, str], None]

_PROVIDERS = Path(__file__).resolve().parents[3] / "catalog" / "providers"
SIDEBAR_PATH = _PROVIDERS / "tushare_document2_sidebar.json"


class ApiMetadataSyncService:
    """Dual-source metadata refresh: wctapi markdown + tushare pro_api SDK."""

    def resolve_doc_ids(self, *, scope: str = "sidebar") -> list[int]:
        if scope == "specs":
            return sorted(int(k) for k in load_api_specs_cache())
        if not SIDEBAR_PATH.is_file():
            return []
        raw = json.loads(SIDEBAR_PATH.read_text(encoding="utf-8"))
        return sorted(
            {
                int(entry["doc_id"])
                for entry in raw.get("entries", [])
                if entry.get("doc_id") is not None
            }
        )

    def patch_page_cache_from_specs(
        self,
        *,
        specs: dict[str, dict[str, Any]] | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Align tushare_doc_pages_cache api/raw_text with wctapi specs."""
        svc = DocPagesSyncService()
        store = specs if specs is not None else load_api_specs_cache()
        pages = svc.load_cache_pages()
        stats = {"updated": 0, "created": 0}
        for doc_key, spec in store.items():
            if not isinstance(spec, dict) or not spec.get("api"):
                continue
            patch = spec_to_page_cache_entry(spec)
            prev = pages.get(doc_key)
            if prev is None:
                stats["created"] += 1
            else:
                stats["updated"] += 1
            pages[doc_key] = {**(prev or {}), **patch}
        if not dry_run:
            svc.write_cache(pages)
        return stats

    def patch_sidebar_from_specs(
        self,
        *,
        specs: dict[str, dict[str, Any]] | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Fix sidebar entry api/min_points from wctapi specs (menu labels kept)."""
        if not SIDEBAR_PATH.is_file():
            return {"updated": 0, "api_fixed": 0, "points_fixed": 0}
        store = specs if specs is not None else load_api_specs_cache()
        raw = json.loads(SIDEBAR_PATH.read_text(encoding="utf-8"))
        stats = {"updated": 0, "api_fixed": 0, "points_fixed": 0}
        for entry in raw.get("entries", []):
            doc_key = str(entry.get("doc_id"))
            spec = store.get(doc_key)
            if not spec or not spec.get("api"):
                continue
            changed = False
            truth_api = str(spec["api"])
            if entry.get("api") != truth_api:
                entry["api"] = truth_api
                entry["resolved"] = True
                stats["api_fixed"] += 1
                changed = True
            spec_pts = spec.get("min_points")
            if spec_pts is not None and entry.get("min_points") != int(spec_pts):
                entry["min_points"] = int(spec_pts)
                entry["min_points_source"] = "wctapi_md"
                stats["points_fixed"] += 1
                changed = True
            if changed:
                stats["updated"] += 1
        if stats["updated"] and not dry_run:
            raw["specs_synced_at"] = datetime.now(timezone.utc).isoformat()
            raw["specs_api_count"] = len(build_api_to_doc_id_map(cache=store))
            SIDEBAR_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return stats

    def run(
        self,
        doc_ids: list[int],
        *,
        token: str | None = None,
        max_calls_per_minute: int | None = None,
        validate_sdk: bool = True,
        sleep_seconds: float = 0.12,
        patch_page_cache: bool = True,
        patch_sidebar: bool = True,
        rebuild_registry: bool = True,
        regenerate_default_proposals: bool = True,
        index_scope: str = "stock_a",
        dry_run: bool = False,
        progress: ProgressFn | None = None,
    ) -> dict[str, Any]:
        def report(pct: int, msg: str) -> None:
            if progress:
                progress(pct, msg)

        report(2, f"Fetching wctapi specs for {len(doc_ids)} doc_ids…")
        spec_result = ApiSpecSyncService().run(
            doc_ids,
            token=token,
            max_calls_per_minute=max_calls_per_minute,
            validate_sdk=validate_sdk and bool(token),
            write_cache=not dry_run,
            sleep_seconds=sleep_seconds,
            progress=lambda pct, msg: report(int(pct * 0.55), msg),
        )

        specs = load_api_specs_cache()
        page_stats: dict[str, int] = {}
        sidebar_stats: dict[str, int] = {}
        registry_count = 0

        if patch_page_cache:
            report(60, "Patching doc_pages_cache from wctapi specs…")
            page_stats = self.patch_page_cache_from_specs(specs=specs, dry_run=dry_run)

        if patch_sidebar:
            report(72, "Patching document/2 sidebar api names…")
            sidebar_stats = self.patch_sidebar_from_specs(specs=specs, dry_run=dry_run)

        if rebuild_registry and not dry_run:
            report(84, "Rebuilding tushare_api_by_doc_id.json…")
            registry_count = DocPagesSyncService().rebuild_api_by_doc_id_file()

        proposals_path: str | None = None
        proposals_count = 0
        if regenerate_default_proposals and not dry_run:
            report(92, "Regenerating tushare_default_proposals.json…")
            out = write_default_proposals_file(index_scope=index_scope)
            proposals_path = str(out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            proposals_count = len(payload.get("items", []))

        if not dry_run:
            from app.services.tia.proposal_enrichment import invalidate_api_meta_cache

            invalidate_api_meta_cache()

        report(
            100,
            f"Metadata sync: {spec_result.get('synced_count', 0)} specs, "
            f"{sidebar_stats.get('api_fixed', 0)} sidebar api fixes",
        )
        return {
            "doc_ids_total": len(doc_ids),
            "spec_sync": spec_result,
            "page_cache": page_stats,
            "sidebar": sidebar_stats,
            "registry_doc_ids": registry_count,
            "default_proposals_path": proposals_path,
            "default_proposals_count": proposals_count,
            "api_to_doc_count": len(build_api_to_doc_id_map(cache=specs)),
            "dry_run": dry_run,
        }
