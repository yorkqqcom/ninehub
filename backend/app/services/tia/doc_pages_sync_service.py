"""Sync Tushare interface doc pages (api + min_points) from document/2 live pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tia_override import TiaOverride
from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions
from app.services.tia.scan.doc_points_resolver import list_doc_ids_needing_live_fetch, resolve_doc_ids_for_scope
from app.services.tia.scan.tushare_doc_page_fetcher import fetch_doc_pages
from app.services.tia.scan.tushare_doc_registry import (
    build_api_by_doc_id,
    resolve_canonical_api_meta,
    resolve_min_points_for_doc_id,
)

_PROVIDERS_DIR = Path(__file__).resolve().parents[2] / "catalog" / "providers"
CACHE_PATH = _PROVIDERS_DIR / "tushare_doc_pages_cache.json"
API_BY_DOC_PATH = _PROVIDERS_DIR / "tushare_api_by_doc_id.json"
SIDEBAR_PATH = _PROVIDERS_DIR / "tushare_document2_sidebar.json"

ProgressFn = Callable[[int, str], None]


class DocPagesSyncService:
    def resolve_doc_ids(self, options: DocPagesSyncOptions) -> list[int]:
        return resolve_doc_ids_for_scope(
            options.scope,
            doc_ids=options.doc_ids,
        )

    def list_stale_doc_ids(self, options: DocPagesSyncOptions) -> list[int]:
        doc_ids = self.resolve_doc_ids(options)
        return list_doc_ids_needing_live_fetch(doc_ids)

    def load_cache_pages(self) -> dict[str, dict]:
        if not CACHE_PATH.is_file():
            return {}
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return dict(raw.get("pages", raw))

    def write_cache(self, pages: dict[str, dict]) -> None:
        payload = {
            "provider": "tushare",
            "source_url": "https://tushare.pro/document/2",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "note": "Live sync from document/2 interface pages (Playwright auth)",
            "page_count": len(pages),
            "pages": pages,
        }
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def merge_fetched_pages(
        self,
        existing: dict[str, dict],
        fetched: dict[str, dict],
    ) -> tuple[dict[str, dict], dict[str, int]]:
        merged = dict(existing)
        stats = {"fetched": len(fetched), "updated": 0, "skipped_error": 0, "with_api": 0, "with_points": 0}
        for doc_key, entry in fetched.items():
            if entry.get("error") and not entry.get("api"):
                prev = merged.get(doc_key)
                if prev and not prev.get("error"):
                    stats["skipped_error"] += 1
                    continue
            merged[doc_key] = entry
            stats["updated"] += 1
            if entry.get("api"):
                stats["with_api"] += 1
            if entry.get("min_points") is not None:
                stats["with_points"] += 1
        return merged, stats

    def rebuild_api_by_doc_id_file(self) -> int:
        by_doc = build_api_by_doc_id()
        entries = sorted(by_doc.values(), key=lambda x: x["doc_id"])
        resolved = sum(1 for e in entries if e.get("api"))
        payload = {
            "provider": "tushare",
            "version": datetime.now(timezone.utc).strftime("%Y-%m-%d-doc-registry"),
            "total": len(entries),
            "resolved_api_count": resolved,
            "entries": entries,
            "by_doc_id": {str(e["doc_id"]): e for e in entries},
        }
        API_BY_DOC_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(entries)

    def patch_sidebar_from_pages(self, pages: dict[str, dict]) -> int:
        if not SIDEBAR_PATH.is_file():
            return 0
        raw = json.loads(SIDEBAR_PATH.read_text(encoding="utf-8"))
        updated = 0
        for entry in raw.get("entries", []):
            doc_key = str(entry.get("doc_id"))
            cached = pages.get(doc_key)
            if not cached or cached.get("error"):
                continue
            changed = False
            if cached.get("api"):
                entry["api"] = cached["api"]
                entry["resolved"] = True
                changed = True
            if cached.get("min_points") is not None:
                entry["min_points"] = int(cached["min_points"])
                entry["min_points_source"] = cached.get("min_points_source") or "doc_page_live"
                changed = True
            if changed:
                updated += 1
        if updated:
            SIDEBAR_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return updated

    def reconcile_overrides_sync(self, session: Session) -> list[dict[str, Any]]:
        mismatches: list[dict[str, Any]] = []
        overrides = list(session.execute(select(TiaOverride)).scalars().all())
        for override in overrides:
            canonical = resolve_canonical_api_meta(override.api_name)
            if not canonical:
                continue
            doc_id = canonical.get("doc_id")
            expected_pts = canonical.get("min_points")
            if doc_id is not None:
                resolved_pts, source = resolve_min_points_for_doc_id(int(doc_id))
                if resolved_pts is not None:
                    expected_pts = resolved_pts
            else:
                source = canonical.get("min_points_source")
            if expected_pts is None or int(override.min_points) == int(expected_pts):
                continue
            row = {
                "api": override.api_name,
                "before": int(override.min_points),
                "after": int(expected_pts),
                "doc_id": doc_id,
                "min_points_source": source,
            }
            mismatches.append(row)
            override.min_points = int(expected_pts)
            expected_url = canonical.get("doc_url")
            if expected_url and override.doc_url != expected_url:
                override.doc_url = expected_url
        return mismatches

    def run(
        self,
        session: Session | None,
        options: DocPagesSyncOptions,
        progress: ProgressFn | None = None,
        *,
        fetch_pages: Callable[..., dict[str, dict]] | None = None,
    ) -> dict[str, Any]:
        def report(pct: int, msg: str) -> None:
            if progress:
                progress(pct, msg)

        doc_ids = self.resolve_doc_ids(options)
        stale = list_doc_ids_needing_live_fetch(doc_ids)
        report(5, f"Resolved {len(doc_ids)} doc_ids ({len(stale)} stale, scope={options.scope})")

        fetcher = fetch_pages or fetch_doc_pages
        fetched: dict[str, dict] = {}

        def on_fetch(doc_id: int, idx: int, total: int) -> None:
            pct = 5 + int(70 * idx / max(total, 1))
            report(pct, f"Fetching doc_id={doc_id} ({idx}/{total})")

        if doc_ids:
            fetched = fetcher(
                doc_ids,
                sleep_seconds=options.sleep_seconds,
                on_progress=on_fetch,
                use_playwright=options.use_playwright,
                login_if_needed=options.login_if_needed,
            )

        existing = self.load_cache_pages()
        merged, merge_stats = self.merge_fetched_pages(existing, fetched)
        report(78, f"Merged cache: {merge_stats['updated']} pages updated")

        if options.dry_run:
            return {
                "dry_run": True,
                "doc_ids_total": len(doc_ids),
                "merge_stats": merge_stats,
                "sample": {k: merged[k] for k in list(merged.keys())[:5]},
            }

        self.write_cache(merged)
        report(82, "Wrote tushare_doc_pages_cache.json")

        registry_count = 0
        sidebar_patched = 0
        if options.rebuild_registry:
            registry_count = self.rebuild_api_by_doc_id_file()
            report(88, f"Rebuilt tushare_api_by_doc_id.json ({registry_count} doc_ids)")

        if options.patch_sidebar:
            sidebar_patched = self.patch_sidebar_from_pages(merged)
            report(92, f"Patched sidebar entries: {sidebar_patched}")

        reconcile_rows: list[dict[str, Any]] = []
        if options.reconcile_overrides and session is not None:
            reconcile_rows = self.reconcile_overrides_sync(session)
            report(96, f"Reconciled {len(reconcile_rows)} override min_points")

        report(
            100,
            f"Doc sync complete: {merge_stats['with_api']} api, {merge_stats['with_points']} min_points",
        )
        result = {
            "doc_ids_total": len(doc_ids),
            "merge_stats": merge_stats,
            "registry_doc_ids": registry_count,
            "sidebar_patched": sidebar_patched,
            "reconcile_overrides": reconcile_rows,
            "cache_path": str(CACHE_PATH),
            "sync_options": options.to_dict(),
            "sync_message": (
                f"Synced {merge_stats['updated']} pages "
                f"({merge_stats['with_points']} min_points, {len(reconcile_rows)} overrides reconciled)"
            ),
        }
        return result
