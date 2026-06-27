#!/usr/bin/env python3
"""Bootstrap TDX L3 activation for bar_1d and optional concept/minute APIs.

Examples:
  python scripts/bootstrap_tdx_bar_1d.py
  python scripts/bootstrap_tdx_bar_1d.py --apis bar_1d concept_index concept_member
  python scripts/bootstrap_tdx_bar_1d.py --apis bar_1m bar_5m
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from browser_bootstrap_lib import activate_sync, approve_if_pending, db_session
from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.tia.constants import api_to_data_type

DEFAULT_APIS = ("bar_1d",)
PROVIDER = "tdx"


def ensure_tdx_proposal(session: Session, api_name: str, *, reason: str) -> TiaProposal:
    row = session.execute(
        select(TiaProposal)
        .where(TiaProposal.api_name == api_name)
        .order_by(TiaProposal.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return row
    data_type = api_to_data_type(api_name, provider=PROVIDER)
    proposal = TiaProposal(
        api_name=api_name,
        status="pending",
        action="review",
        reason=reason,
        data_type=data_type,
    )
    session.add(proposal)
    session.flush()
    print(f"  created proposal for {api_name} -> {data_type} id={proposal.id}")
    return proposal


def activate_apis(session: Session, apis: list[str], *, reason: str) -> int:
    failed = 0
    for api in apis:
        print(f"\n=== activate tdx/{api} ===")
        try:
            proposal = ensure_tdx_proposal(session, api, reason=reason)
            print(f"  proposal id={proposal.id} status={proposal.status}")
            if proposal.status == "applied":
                print("  already applied")
                continue
            approve_if_pending(session, proposal)
            session.commit()
            reapply = proposal.status in ("applied", "failed")
            result = activate_sync(session, proposal.id, reapply=reapply)
            status = session.execute(
                text("select status from tia_proposals where id=:id"),
                {"id": proposal.id},
            ).scalar()
            print(f"  activation -> {status}, data_type={result.get('data_type')}")
            for step, meta in (result.get("steps") or {}).items():
                if isinstance(meta, dict) and meta.get("status") == "failed":
                    print(f"    FAIL {step}: {meta.get('error', '')[:200]}")
            if status != "applied":
                failed += 1
        except Exception as exc:
            session.rollback()
            failed += 1
            print(f"  ERROR: {exc}")
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap TDX L3 activation")
    parser.add_argument(
        "--apis",
        nargs="*",
        default=list(DEFAULT_APIS),
        help="TDX api_name list (default: bar_1d)",
    )
    parser.add_argument(
        "--reason",
        default="tdx_bootstrap",
        help="Proposal reason tag",
    )
    args = parser.parse_args()
    apis = list(dict.fromkeys(args.apis))
    print(f"TDX bootstrap APIs: {', '.join(apis)}")
    with db_session() as session:
        failed = activate_apis(session, apis, reason=args.reason)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
