"""Seed doc pages cache from sidebar — stubs only (no fabricated min_points).

Live min_points must come from document/2 via sync_tushare_doc_pages_cache.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.tushare_doc_catalog import load_document2_sidebar_raw  # noqa: E402
from app.services.tia.scan.tushare_doc_registry import (  # noqa: E402
    load_api_by_doc_id,
    resolve_sidebar_entry,
)

CACHE_PATH = ROOT / "app" / "catalog" / "providers" / "tushare_doc_pages_cache.json"
DEPRECATED = frozenset({108})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed doc page stubs (api only) — run sync_tushare_doc_pages_cache for min_points"
    )
    parser.add_argument("--scope", choices=("resolved", "all"), default="resolved")
    args = parser.parse_args()

    raw = load_document2_sidebar_raw()
    entries = raw.get("entries", [])
    if args.scope == "resolved":
        entries = [e for e in entries if e.get("resolved")]

    api_by_doc = load_api_by_doc_id()
    pages: dict[str, dict] = {}
    for entry in entries:
        doc_id = int(entry["doc_id"])
        if doc_id in DEPRECATED:
            continue
        enriched = resolve_sidebar_entry(entry, api_by_doc=api_by_doc)
        api = enriched.get("api")
        if not api:
            continue
        pages[str(doc_id)] = {
            "api": api,
            "source": "sidebar_seed_stub",
            "note": "Run sync_tushare_doc_pages_cache.py to fetch min_points from document/2",
        }

    payload = {
        "provider": "tushare",
        "source_url": "https://tushare.pro/document/2",
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "note": "Stubs only — min_points require live document/2 sync",
        "page_count": len(pages),
        "pages": pages,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Seeded {len(pages)} stubs -> {CACHE_PATH}")


if __name__ == "__main__":
    main()
