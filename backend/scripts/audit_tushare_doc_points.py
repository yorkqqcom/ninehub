"""CLI: audit Tushare doc-page min_points coverage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.doc_points_audit import run_doc_points_coverage_audit  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit min_points coverage for document/2 APIs")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    report = run_doc_points_coverage_audit()
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return

    summary = report.audit_summary
    print(f"Resolved APIs: {report.total_resolved_apis}")
    print(f"Missing min_points: {len(report.missing_min_points)}")
    print(f"Stale doc pages: {len(report.stale_doc_pages)}")
    print(f"Parse gaps: {len(report.parse_gaps)}")
    print(f"Bundled mismatches: {len(report.bundled_mismatches)}")
    print(f"Doc-id conflicts: {len(report.doc_id_conflicts)}")
    print(f"Doc-id multi-api (P0/P1): {len(report.doc_id_multi_api)}")
    print(f"Sidebar drift (P2): {len(report.sidebar_drift)}")
    print(
        "Audit summary: "
        f"page_body_multi={summary.page_body_multi_count} "
        f"cache_mismatch={summary.cache_api_mismatch_count} "
        f"sidebar_drift={summary.sidebar_drift_count}"
    )

    if report.missing_min_points:
        print("\n-- missing min_points --")
        for row in report.missing_min_points[:20]:
            print(f"  {row['api']} doc={row['doc_id']}")

    if report.parse_gaps:
        print("\n-- parse gaps --")
        for row in report.parse_gaps[:20]:
            print(f"  {row['api']} doc={row['doc_id']}")

    if report.doc_id_conflicts:
        print("\n-- doc-id conflicts --")
        for row in report.doc_id_conflicts[:20]:
            print(f"  {row}")

    if report.doc_id_multi_api:
        print("\n-- doc-id multi-api (blocking P0/P1) --")
        for row in report.doc_id_multi_api[:30]:
            print(f"  {row}")

    if report.sidebar_drift:
        print("\n-- sidebar drift (P2 informational) --")
        for row in report.sidebar_drift[:30]:
            print(f"  {row}")

    if not report.has_issues:
        print("\nNo blocking coverage issues detected.")
    sys.exit(1 if report.missing_min_points or report.parse_gaps or report.doc_id_multi_api else 0)


if __name__ == "__main__":
    main()
