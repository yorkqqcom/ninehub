"""CLI: audit TIA proposal api_name vs document/2 wctapi page interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.tia_proposal import TiaProposal  # noqa: E402
from app.services.tia.proposal_doc_link_audit import audit_proposals  # noqa: E402
from app.services.tia.proposal_enrichment import invalidate_api_meta_cache  # noqa: E402


def _load_db_proposals() -> list[TiaProposal]:
    from app.core.database import sync_engine

    with Session(sync_engine) as session:
        return list(session.execute(select(TiaProposal).order_by(TiaProposal.id)).scalars().all())


def _load_seed_proposals() -> list[dict]:
    path = ROOT / "app" / "catalog" / "providers" / "tushare_default_proposals.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items", [])


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit proposal api_name vs wctapi doc page")
    parser.add_argument("--source", choices=("db", "seed", "both"), default="db")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument("--live", action="store_true", help="Reserved: re-fetch wctapi (uses bundled cache)")
    args = parser.parse_args()

    invalidate_api_meta_cache()
    items: list = []
    if args.source in ("db", "both"):
        try:
            items.extend(_load_db_proposals())
        except Exception as exc:
            print(f"DB load failed: {exc}", file=sys.stderr)
            if args.source == "db":
                sys.exit(1)
    if args.source in ("seed", "both"):
        items.extend(_load_seed_proposals())

    report = audit_proposals(items)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return

    print(
        f"对照完成: 总计 {report.total} | 一致 {report.ok_count} | "
        f"文档不一致 {report.doc_mismatch_count} | 无 wctapi {report.no_spec_count}"
    )
    if report.doc_mismatch_count or report.no_spec_count:
        print("\n-- 需处理 --")
        for row in report.rows:
            if row.status == "ok":
                continue
            pid = f"id={row.proposal_id} " if row.proposal_id else ""
            print(
                f"  {pid}{row.api_name} [{row.status}] "
                f"doc={row.doc_id} page_api={row.page_api} | {row.message or ''}"
            )


if __name__ == "__main__":
    main()
