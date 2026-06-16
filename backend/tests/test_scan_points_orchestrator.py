"""Orchestrator integration: full scan includes points_coverage."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.platform.job_service import PlatformJobService
from app.services.tia.scan.orchestrator import TiaScanOrchestrator
from app.services.tia.scan.types import ScanOptions


def test_full_scan_result_includes_points_coverage() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    opts = ScanOptions(
        mode="full",
        probe=False,
        index_source="document2",
        index_scope="stock_a",
        sync_doc_pages=False,
    )
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    cov = result.get("points_coverage")
    assert isinstance(cov, dict)
    assert cov.get("sync_doc_pages") is False
    assert "index_apis_total" in cov
    assert cov["index_apis_total"] == result["official_count"]
    session.close()
