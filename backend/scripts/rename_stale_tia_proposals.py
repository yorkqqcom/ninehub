"""CLI: rename stale TIA proposal api_name to current wctapi interface names."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.platform_job import PlatformJob  # noqa: F401,E402
from app.models.tia_proposal import TiaProposal  # noqa: E402
from app.models.user import User  # noqa: F401,E402
from app.services.tia.proposal_doc_link_audit import (  # noqa: E402
    audit_proposals,
    rename_stale_proposal_apis_sync,
)
from app.services.tia.proposal_enrichment import invalidate_api_meta_cache  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Rename stale TIA proposal api names")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL") or "postgresql://ninehub:ninehub@127.0.0.1:5432/ninehub"
    engine = create_engine(url.replace("+asyncpg", ""))

    with Session(engine) as session:
        if args.dry_run:
            rows = list(
                session.execute(
                    select(TiaProposal.id, TiaProposal.api_name).order_by(TiaProposal.id)
                ).all()
            )
            from app.services.tia.proposal_doc_link_audit import STALE_API_RENAME_MAP

            preview = [
                {"id": pid, "api_name": api, "target": STALE_API_RENAME_MAP[api]}
                for pid, api in rows
                if api in STALE_API_RENAME_MAP
            ]
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return

        results = rename_stale_proposal_apis_sync(session)
        session.commit()
        invalidate_api_meta_cache()
        all_proposals = list(session.execute(select(TiaProposal)).scalars().all())
        post = audit_proposals(all_proposals)

    payload = {
        "results": [r.to_dict() for r in results],
        "audit_after": {
            "total": post.total,
            "ok_count": post.ok_count,
            "issues": [r.to_dict() for r in post.rows if r.status != "ok"],
        },
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    for r in results:
        print(f"id={r.proposal_id} [{r.action}] {r.message}")
    print(
        f"\n对照结果: 总计 {post.total} | 一致 {post.ok_count} | "
        f"问题 {post.doc_mismatch_count + post.no_spec_count}"
    )


if __name__ == "__main__":
    main()
