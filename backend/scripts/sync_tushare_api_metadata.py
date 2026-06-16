"""Sync Tushare API metadata: wctapi markdown + optional SDK validation.

Updates bundled:
  - tushare_api_specs_cache.json (fields, params, min_points, sample code)
  - tushare_doc_pages_cache.json (api + raw_text for doc_id resolution)
  - tushare_document2_sidebar.json (correct api names per doc_id)
  - tushare_api_by_doc_id.json
  - tushare_default_proposals.json

Run:
  python scripts/sync_tushare_api_metadata.py
  python scripts/sync_tushare_api_metadata.py --no-sdk
  python scripts/sync_tushare_api_metadata.py --doc-id 48 --doc-id 79
  python scripts/sync_tushare_api_metadata.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.api_metadata_sync_service import ApiMetadataSyncService  # noqa: E402


def _resolve_token() -> str | None:
    return os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_DOC_TOKEN")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Tushare API metadata (wctapi + SDK)")
    parser.add_argument("--scope", choices=("sidebar", "specs", "union"), default="union")
    parser.add_argument("--doc-id", type=int, action="append", dest="doc_ids")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--no-sdk", action="store_true", help="Skip tushare pro_api validation")
    parser.add_argument("--no-page-cache", action="store_true")
    parser.add_argument("--no-sidebar", action="store_true")
    parser.add_argument("--no-registry", action="store_true")
    parser.add_argument("--no-proposals", action="store_true")
    parser.add_argument("--index-scope", choices=("stock_a", "mixed"), default="stock_a")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    svc = ApiMetadataSyncService()
    if args.doc_ids:
        doc_ids = sorted(set(args.doc_ids))
    elif args.scope == "sidebar":
        doc_ids = svc.resolve_doc_ids(scope="sidebar")
    elif args.scope == "specs":
        doc_ids = svc.resolve_doc_ids(scope="specs")
    else:
        doc_ids = sorted(
            set(svc.resolve_doc_ids(scope="sidebar")) | set(svc.resolve_doc_ids(scope="specs"))
        )

    if not doc_ids:
        print("No doc_ids to sync", file=sys.stderr)
        sys.exit(1)

    token = None if args.no_sdk else _resolve_token()
    if not args.no_sdk and not token:
        print("TUSHARE_TOKEN not set — SDK validation skipped", file=sys.stderr)

    def progress(pct: int, msg: str) -> None:
        print(f"[{pct:3d}%] {msg}")

    result = svc.run(
        doc_ids,
        token=token,
        validate_sdk=not args.no_sdk,
        sleep_seconds=args.sleep,
        patch_page_cache=not args.no_page_cache,
        patch_sidebar=not args.no_sidebar,
        rebuild_registry=not args.no_registry,
        regenerate_default_proposals=not args.no_proposals,
        index_scope=args.index_scope,
        dry_run=args.dry_run,
        progress=progress,
    )
    print(
        f"Done: synced={result['spec_sync'].get('synced_count')} "
        f"errors={result['spec_sync'].get('error_count')} "
        f"sidebar_api_fixed={result['sidebar'].get('api_fixed', 0)} "
        f"api_map={result['api_to_doc_count']}"
    )


if __name__ == "__main__":
    main()
