"""Bootstrap document/2 min_points from live page snapshots into cache.

Pipeline (100-iteration design — see doc_points_bootstrap_service.py):
  1. Load sidebar canonical doc_ids (76 APIs)
  2. For each page: plain text → extract_access_min_points (never sidebar hints)
  3. Merge into tushare_doc_pages_cache.json
  4. Emit coverage audit

Usage:
  python scripts/bootstrap_tushare_doc_points.py --from-snapshot tests/fixtures/tushare_doc_pages_live_snapshot.json
  python scripts/bootstrap_tushare_doc_points.py --audit-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.doc_points_bootstrap_service import (  # noqa: E402
    bootstrap_doc_points_from_snapshot,
    list_canonical_doc_targets,
    run_bootstrap_audit,
)

DEFAULT_SNAPSHOT = ROOT / "tests" / "fixtures" / "tushare_doc_pages_live_snapshot.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap min_points from document/2 page snapshots")
    parser.add_argument("--from-snapshot", type=Path, help="JSON snapshot {pages: {doc_id: {plain_text|markdown}}}")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.audit_only:
        report = run_bootstrap_audit()
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"targets={report['targets']} with_points={report['with_points']} missing={report['missing']}")
            for row in report.get("missing_rows", [])[:25]:
                print(f"  doc={row['doc_id']} api={row['api']}")
        return

    snapshot_path = args.from_snapshot or DEFAULT_SNAPSHOT
    if not snapshot_path.is_file():
        targets = list_canonical_doc_targets()
        print(f"Snapshot missing: {snapshot_path}")
        print(f"Canonical doc targets: {len(targets)} — fetch pages first, then re-run with --from-snapshot")
        sys.exit(1)

    result = bootstrap_doc_points_from_snapshot(snapshot_path, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"merged={result['merged']} with_points={result['with_points']} "
            f"no_points={result['no_points']} dry_run={args.dry_run}"
        )
        if result.get("sample_gaps"):
            print("-- still no numeric 积分 on page --")
            for row in result["sample_gaps"][:15]:
                print(f"  doc={row['doc_id']} api={row['api']}")


if __name__ == "__main__":
    main()
