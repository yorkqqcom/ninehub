"""Validate PLAIN_SEEDS against doc_pages_cache (Phase C data governance).

Usage:
  python scripts/validate_plain_doc_seeds.py
  python scripts/validate_plain_doc_seeds.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.tushare_doc_registry import (  # noqa: E402
    load_doc_pages_cache,
    parse_api_name_from_doc_text,
)
from scripts._live_doc_plain_seeds import PLAIN_SEEDS  # noqa: E402


def collect_seed_cache_mismatches() -> list[dict]:
    cache = load_doc_pages_cache()
    rows: list[dict] = []
    for doc_id, plain in sorted(PLAIN_SEEDS.items()):
        seed_api = parse_api_name_from_doc_text(plain)
        cached = cache.get(str(doc_id), {})
        cache_api = parse_api_name_from_doc_text(cached.get("raw_text", "")) or cached.get("api")
        if seed_api and cache_api and str(seed_api) != str(cache_api):
            rows.append(
                {
                    "doc_id": doc_id,
                    "seed_api": seed_api,
                    "cache_api": cache_api,
                    "url": f"https://tushare.pro/document/2?doc_id={doc_id}",
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate plain doc seeds vs page cache")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    mismatches = collect_seed_cache_mismatches()
    payload = {
        "seed_count": len(PLAIN_SEEDS),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"seeds={payload['seed_count']} mismatches={payload['mismatch_count']}")
        for row in mismatches:
            print(
                f"  doc_id={row['doc_id']} seed={row['seed_api']} cache={row['cache_api']}"
            )
    sys.exit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
