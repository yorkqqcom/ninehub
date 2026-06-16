"""Stale pending proposals for local override APIs are reconciled on scan."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal
from app.services.platform.job_service import PlatformJobService
from app.services.tia.proposal_service import TiaProposalService
from app.services.tia.service import TIAService
from app.services.tia.scan.types import ScanOptions


def test_scan_rejects_pending_proposals_for_local_override_apis() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(
        TiaOverride(
            api_name="daily",
            data_type="tushare_daily",
            label="Daily",
            min_points=120,
        )
    )
    session.add(TiaProposal(api_name="daily", status="pending", reason="new_on_official"))
    session.add(TiaProposal(api_name="balancesheet", status="pending", reason="new_on_official"))
    session.commit()

    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    result = TIAService().execute_scan_sync(
        session,
        job.id,
        ScanOptions(probe=False, mode="full", index_source="bundled", index_scope="mixed"),
    )

    assert result["proposals_reconciled"] == 1
    daily = session.execute(select(TiaProposal).where(TiaProposal.api_name == "daily")).scalar_one()
    assert daily.status == "rejected"
    assert daily.reason == "already_in_local_catalog"

    balancesheet = session.execute(
        select(TiaProposal).where(TiaProposal.api_name == "balancesheet")
    ).scalar_one()
    assert balancesheet.status == "pending"
    assert balancesheet.reason == "new_on_official"
    assert result["proposals_pending"] >= 1
    session.close()


def test_reconcile_local_catalog_proposals_sync_rejects_pending() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(TiaProposal(api_name="stock_basic", status="pending", reason="new_on_official"))
    session.add(TiaProposal(api_name="income", status="approved"))
    session.commit()

    svc = TiaProposalService()
    closed = svc.reconcile_local_catalog_proposals_sync(session, ["stock_basic", "daily"])
    assert closed == 1
    row = session.execute(select(TiaProposal).where(TiaProposal.api_name == "stock_basic")).scalar_one()
    assert row.status == "rejected"
    assert row.reason == "already_in_local_catalog"
    session.close()
