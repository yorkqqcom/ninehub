"""Sync Tushare interface doc pages into tushare_doc_pages_cache.json.

Requires Playwright + login (storage state or TUSHARE_DOC_USERNAME/PASSWORD):

  pip install playwright && playwright install chromium
  # optional one-time login storage:
  # set TUSHARE_DOC_USERNAME / TUSHARE_DOC_PASSWORD in .env

  python scripts/sync_tushare_doc_pages_cache.py --scope all
  python scripts/sync_tushare_doc_pages_cache.py --doc-id 26 --doc-id 28
  python scripts/sync_tushare_doc_pages_cache.py --dry-run --scope resolved
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.doc_pages_sync_service import DocPagesSyncService  # noqa: E402
from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Tushare interface doc pages (live)")
    parser.add_argument("--stats", action="store_true", help="Print cache stats only")
    parser.add_argument("--scope", choices=("resolved", "all"), default="all")
    parser.add_argument("--doc-id", type=int, action="append", dest="doc_ids")
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--no-playwright", action="store_true")
    parser.add_argument("--no-login", action="store_true")
    parser.add_argument("--no-rebuild", action="store_true")
    parser.add_argument("--no-sidebar", action="store_true")
    parser.add_argument("--no-reconcile", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Strip fabricated sidebar_seed min_points from cache (no network)",
    )
    args = parser.parse_args()

    svc = DocPagesSyncService()
    if args.sanitize:
        from app.services.tia.scan.doc_points_resolver import sanitize_stale_cache_entry
        from app.services.tia.scan.tushare_doc_registry import _load_json

        pages = svc.load_cache_pages()
        api_by_doc = {
            int(entry["doc_id"]): entry["api"]
            for entry in _load_json("tushare_document2_sidebar.json").get("entries", [])
            if entry.get("doc_id") and entry.get("api")
        }
        cleaned = {}
        for key, entry in pages.items():
            row = sanitize_stale_cache_entry(entry)
            try:
                doc_id = int(key)
                if doc_id in api_by_doc:
                    row["api"] = api_by_doc[doc_id]
            except ValueError:
                pass
            cleaned[key] = row
        if not args.dry_run:
            svc.write_cache(cleaned)
        print(f"sanitized pages={len(cleaned)} dry_run={args.dry_run}")
        return

    if args.stats:
        pages = svc.load_cache_pages()
        with_api = sum(1 for p in pages.values() if p.get("api"))
        with_pts = sum(1 for p in pages.values() if p.get("min_points") is not None)
        errors = sum(1 for p in pages.values() if p.get("error"))
        print(f"pages={len(pages)} with_api={with_api} with_min_points={with_pts} errors={errors}")
        return

    opts = DocPagesSyncOptions(
        scope=args.scope,
        doc_ids=args.doc_ids,
        sleep_seconds=args.sleep,
        use_playwright=not args.no_playwright,
        login_if_needed=not args.no_login,
        rebuild_registry=not args.no_rebuild,
        patch_sidebar=not args.no_sidebar,
        reconcile_overrides=not args.no_reconcile,
        dry_run=args.dry_run,
    )

    def progress(pct: int, msg: str) -> None:
        print(f"[{pct}%] {msg}")

    result = svc.run(None, opts, progress)
    print(result.get("sync_message") or result)


if __name__ == "__main__":
    main()
