"""Shared helpers for Data Browser bootstrap scripts."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import sync_engine
from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import TiaActivationService
from app.services.tia.constants import api_to_data_type
from app.services.tia.credentials import require_tushare_token, resolve_tushare_scan_credentials
from app.services.tia.scan.tushare_doc_registry import resolve_api_meta


def db_session() -> Session:
    """Open sync session via Settings (.env); same DB as setup_collect_workflows."""
    return Session(sync_engine)


def ensure_proposal(session: Session, api_name: str, *, reason: str) -> TiaProposal:
    row = session.execute(
        select(TiaProposal)
        .where(TiaProposal.api_name == api_name)
        .order_by(TiaProposal.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return row
    meta = resolve_api_meta(api_name)
    proposal = TiaProposal(
        api_name=api_name,
        status="pending",
        action="review",
        reason=reason,
        data_type=api_to_data_type(api_name),
    )
    session.add(proposal)
    session.flush()
    print(f"  created proposal for {api_name} id={proposal.id} min_points={meta.get('min_points')}")
    return proposal


def approve_if_pending(session: Session, proposal: TiaProposal) -> None:
    if proposal.status != "pending":
        return
    admin_id = session.execute(text("select id from users where role='admin' limit 1")).scalar()
    if admin_id is None:
        raise RuntimeError("No admin user found; run init_db.py first")
    proposal.status = "approved"
    proposal.approved_by_id = int(admin_id)
    session.flush()
    print(f"  approved {proposal.api_name} id={proposal.id}")


def activate_sync(session: Session, proposal_id: int, *, reapply: bool) -> dict:
    jobs = PlatformJobService()
    job = jobs.create_sync(session, "tia_activate")
    job.result_json = {"proposal_id": proposal_id, "reapply": reapply}
    session.commit()
    return TiaActivationService().execute_activation_sync(session, job.id)


def get_override(session: Session, api_name: str) -> TiaOverride | None:
    return session.execute(
        select(TiaOverride).where(TiaOverride.api_name == api_name).limit(1)
    ).scalar_one_or_none()


def schema_of(override: TiaOverride) -> dict:
    return dict((override.override_json or {}).get("schema") or {})


def check_account_points(session: Session, min_points: int, label: str) -> None:
    creds = resolve_tushare_scan_credentials(session)
    points = int(creds.get("account_points") or 0)
    print(f"Tushare account points: {points} (required {min_points} for {label})")
    if points < min_points:
        print(f"  WARN: 积分不足 {min_points}，{label} 调用可能失败")
    require_tushare_token(creds)


def row_count(session: Session, table: str) -> int:
    try:
        return int(session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())
    except Exception:
        return -1
