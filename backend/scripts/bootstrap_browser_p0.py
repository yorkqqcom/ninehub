#!/usr/bin/env python3
"""Bootstrap Data Browser P0: approve+activate daily/trade_cal, optional initial collect."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from browser_bootstrap_lib import db_session

from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import TiaActivationService
from app.services.tia.constants import api_to_data_type
from app.services.tia.override_service import TiaOverrideService
from app.tasks.sync_tasks import run_collect

P0_APIS = ("daily", "trade_cal")
P0_BROWSE_APIS = ("stock_basic", "daily", "adj_factor")


def _ensure_proposal(session: Session, api_name: str) -> TiaProposal:
    row = session.execute(
        select(TiaProposal)
        .where(TiaProposal.api_name == api_name)
        .order_by(TiaProposal.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return row
    proposal = TiaProposal(
        api_name=api_name,
        status="pending",
        action="review",
        reason="browser_p0_bootstrap",
        data_type=api_to_data_type(api_name),
    )
    session.add(proposal)
    session.flush()
    print(f"  created proposal for {api_name} id={proposal.id}")
    return proposal


def _approve_if_pending(session: Session, proposal: TiaProposal) -> None:
    if proposal.status != "pending":
        return
    admin_id = session.execute(text("select id from users where role='admin' limit 1")).scalar()
    if admin_id is None:
        raise RuntimeError("No admin user found; run init_db.py first")
    proposal.status = "approved"
    proposal.approved_by_id = int(admin_id)
    session.flush()
    print(f"  approved {proposal.api_name} id={proposal.id}")


def _activate_sync(session: Session, proposal_id: int, *, reapply: bool) -> dict:
    jobs = PlatformJobService()
    job = jobs.create_sync(session, "tia_activate")
    job.result_json = {"proposal_id": proposal_id, "reapply": reapply}
    session.commit()
    svc = TiaActivationService()
    return svc.execute_activation_sync(session, job.id)


def _load_handlers(session: Session) -> None:
    TiaOverrideService().load_all_into_registry_sync(session)


def _collect_if_empty(session: Session, data_type: str) -> None:
    count = session.execute(text(f'SELECT COUNT(*) FROM "{data_type}"')).scalar_one()
    if count and int(count) > 0:
        print(f"  {data_type} already has {count} rows, skip collect")
        return
    task_id = session.execute(
        text("select id from sync_tasks where data_type=:dt limit 1"),
        {"dt": data_type},
    ).scalar()
    if task_id is None:
        print(f"  no sync_task for {data_type}")
        return
    print(f"  collecting {data_type} (task_id={task_id})…")
    result = run_collect(int(task_id))
    print(f"  collect -> {result}")


def _enable_browse(session: Session, api_name: str) -> None:
    svc = TiaOverrideService()
    try:
        override = svc.get_by_api_sync(session, api_name)
    except Exception:
        return
    if not override.is_activated:
        return
    oj = dict(override.override_json or {})
    if oj.get("browse_enabled"):
        print(f"  browse already enabled: {api_name}")
        return
    oj["browse_enabled"] = True
    override.override_json = oj
    from app.services.tia.schema_inference import schema_to_catalog_columns, schema_to_catalog_filters

    schema = oj.get("schema") or {}
    svc.apply_to_registry(
        override,
        columns=schema_to_catalog_columns(schema) if schema else None,
        filters=schema_to_catalog_filters(schema) if schema else None,
        browse_enabled=True,
    )
    session.commit()
    print(f"  browse enabled: {api_name}")


def bootstrap(*, collect_only: bool) -> int:
    session = db_session()
    failed = 0

    if not collect_only:
        for api in P0_APIS:
            print(f"\n=== activate {api} ===")
            try:
                proposal = _ensure_proposal(session, api)
                print(f"  proposal id={proposal.id} status={proposal.status}")
                if proposal.status == "applied":
                    print("  already applied")
                    continue
                _approve_if_pending(session, proposal)
                session.commit()
                reapply = proposal.status in ("applied", "failed")
                result = _activate_sync(session, proposal.id, reapply=reapply)
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

    print("\n=== collect P0 tables ===")
    _load_handlers(session)
    for dt in ("tushare_trade_cal", "tushare_daily"):
        try:
            _collect_if_empty(session, dt)
        except Exception as exc:
            failed += 1
            print(f"  ERROR collecting {dt}: {exc}")

    print("\n=== enable browse (P0) ===")
    for api in P0_BROWSE_APIS:
        try:
            _enable_browse(session, api)
        except Exception as exc:
            print(f"  WARN browse {api}: {exc}")

    session.close()
    print(f"\nDone. failed={failed}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap browser P0 TIA types")
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Skip activation; only load handlers and collect empty P0 tables",
    )
    parser.add_argument(
        "--browse-only",
        action="store_true",
        help="Only enable browse on P0 catalog types (sidebar entry)",
    )
    args = parser.parse_args()
    if args.browse_only:
        session = db_session()
        for api in P0_BROWSE_APIS:
            _enable_browse(session, api)
        session.close()
        raise SystemExit(0)
    raise SystemExit(bootstrap(collect_only=args.collect_only))


if __name__ == "__main__":
    main()
