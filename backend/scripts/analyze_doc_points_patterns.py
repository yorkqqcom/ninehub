"""Analyze document/2 pages for min_points pattern discovery (50-iteration audit)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.doc_points_bootstrap_service import list_canonical_doc_targets  # noqa: E402
from app.services.tia.scan.min_points_extractor import discover_point_audit  # noqa: E402
from scripts._live_doc_plain_seeds import PLAIN_SEEDS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Pattern discovery audit on doc page seeds")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--gaps-only", action="store_true", help="Only pages with candidates but no extract")
    args = parser.parse_args()

    targets = {t["doc_id"]: t["api"] for t in list_canonical_doc_targets()}
    rows: list[dict] = []
    for doc_id, api in sorted(targets.items()):
        plain = PLAIN_SEEDS.get(doc_id, "")
        if not plain:
            rows.append({"doc_id": doc_id, "api": api, "status": "no_seed"})
            continue
        audit = discover_point_audit(plain)
        status = "ok"
        if audit["extracted_min_points"] is None:
            status = "no_extract" if audit["candidates"] or audit["points_section"] else "no_points_on_page"
        row = {
            "doc_id": doc_id,
            "api": api,
            "status": status,
            **audit,
        }
        if args.gaps_only and status != "no_extract":
            continue
        rows.append(row)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    ok = sum(1 for r in rows if r.get("status") == "ok")
    no_page = sum(1 for r in rows if r.get("status") == "no_points_on_page")
    no_seed = sum(1 for r in rows if r.get("status") == "no_seed")
    gaps = sum(1 for r in rows if r.get("status") == "no_extract")
    print(f"targets={len(targets)} extracted={ok} no_page={no_page} gaps={gaps} no_seed={no_seed}")
    for row in rows:
        if row.get("status") == "no_extract":
            print(f"  GAP doc={row['doc_id']} api={row['api']} section={row.get('points_section')!r}")
            for c in row.get("candidates", []):
                print(f"    candidate {c['value']}: {c['snippet']}")


if __name__ == "__main__":
    main()
