#!/usr/bin/env python3
"""Approve + L3-activate TIA APIs (sync). Use after scan or when setup_collect_workflows preflight fails.

Examples:
  python scripts/bootstrap_tia_apis.py fina_indicator stk_limit stk_managers
  python scripts/bootstrap_tia_apis.py --missing-workflows
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from browser_bootstrap_lib import activate_sync, approve_if_pending, db_session, ensure_proposal
from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.workflow.collect_batch import TDX_WORKFLOW_APIS, TUSHARE_WORKFLOW_APIS

WORKFLOW_APIS = TUSHARE_WORKFLOW_APIS
DEFAULT_MISSING = ("fina_indicator", "stk_limit", "stk_managers")


def _missing_workflow_apis(session: Session) -> list[str]:
    rows = session.execute(
        select(TiaOverride.api_name).where(TiaOverride.api_name.in_(WORKFLOW_APIS))
    ).scalars().all()
    return sorted(set(WORKFLOW_APIS) - set(rows))


def activate_apis(session: Session, apis: list[str], *, reason: str) -> int:
    failed = 0
    for api in apis:
        print(f"\n=== activate {api} ===")
        try:
            proposal = ensure_proposal(session, api, reason=reason)
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
    parser = argparse.ArgumentParser(description="Bootstrap TIA L3 activation for named APIs")
    parser.add_argument(
        "apis",
        nargs="*",
        help="Tushare api_name list (e.g. fina_indicator stk_limit stk_managers)",
    )
    parser.add_argument(
        "--missing-workflows",
        action="store_true",
        help="Activate all workflow APIs missing from tia_overrides",
    )
    args = parser.parse_args()

    session = db_session()
    if args.missing_workflows:
        apis = _missing_workflow_apis(session)
        if not apis:
            print("All workflow APIs already in tia_overrides.")
            session.close()
            return 0
        print(f"Missing {len(apis)} Tushare workflow API(s): {', '.join(apis)}")
        skipped = sorted(TDX_WORKFLOW_APIS)
        if skipped:
            print(
                f"Note: TDX APIs ({', '.join(skipped)}) are excluded; "
                "run python scripts/bootstrap_tdx_bar_1d.py instead"
            )
        reason = "workflow_bootstrap"
    elif args.apis:
        apis = list(args.apis)
        reason = "tia_api_bootstrap"
    else:
        apis = list(DEFAULT_MISSING)
        reason = "tia_api_bootstrap"
        print(f"No apis given; defaulting to: {', '.join(apis)}")

    failed = activate_apis(session, apis, reason=reason)
    session.close()
    print(f"\nDone. failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
