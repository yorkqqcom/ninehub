"""TIA L1-L3 governance tests."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.platform_job import PlatformJob
from app.models.tia_proposal import TiaProposal
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import ACTIVATION_STEPS, TiaActivationService
from app.services.tia.preflight_test_service import PreflightTestResult, TiaPreflightTestService
from app.services.tia.scaffold_service import TiaScaffoldService
from app.catalog.registry import CATALOG_REGISTRY, get_data_type_entry

INCOME_LIVE_FIELDS = [
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "basic_eps",
    "total_revenue",
    "revenue",
    "n_income",
]


def _mock_income_preflight():
    result = PreflightTestResult(
        api_name="income",
        passed=True,
        checks=[],
        actual_fields=INCOME_LIVE_FIELDS,
    )
    return patch.object(TiaPreflightTestService, "run", return_value=result)


@pytest.mark.asyncio
async def test_review_proposal_approve(client: AsyncClient, db_session) -> None:
    proposal = TiaProposal(api_name="income", status="pending", action="review")
    db_session.add(proposal)
    await db_session.commit()
    await db_session.refresh(proposal)

    response = await client.patch(
        f"/api/v1/tia/proposals/{proposal.id}",
        json={"status": "approved", "note": "looks good", "domain": "financial"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["data_type"] == "tushare_income"


@pytest.mark.asyncio
async def test_scaffold_download(client: AsyncClient, db_session) -> None:
    proposal = TiaProposal(api_name="income", status="pending")
    db_session.add(proposal)
    await db_session.commit()
    await db_session.refresh(proposal)
    await client.patch(
        f"/api/v1/tia/proposals/{proposal.id}",
        json={"status": "approved"},
    )
    response = await client.get(f"/api/v1/tia/proposals/{proposal.id}/scaffold")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"


def test_scaffold_zip_content() -> None:
    from app.services.tia.override_service import TiaOverrideService

    override = TiaOverrideService().build_override_from_api("income")
    content = TiaScaffoldService().build_zip(override)
    assert len(content) > 100
    assert content[:2] == b"PK"


def test_l3_activation_sync() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    proposal = TiaProposal(
        api_name="income",
        status="approved",
        data_type="tia_income",
        action="review",
    )
    session.add(proposal)
    session.commit()

    from app.services.tia.override_service import TiaOverrideService

    override = TiaOverrideService().build_override_from_api("income")
    session.add(override)
    session.commit()

    jobs = PlatformJobService()
    job = jobs.create_sync(session, "tia_activate")
    job.result_json = {"proposal_id": proposal.id, "reapply": False}
    session.commit()

    service = TiaActivationService()
    with _mock_income_preflight():
        result = service.execute_activation_sync(session, job.id)
    assert result["data_type"] == "tia_income"
    assert get_data_type_entry("tia_income") is not None
    for step in ACTIVATION_STEPS:
        assert result["steps"][step]["status"] == "success"

    updated = session.get(TiaProposal, proposal.id)
    assert updated.status == "applied"
    session.close()
    CATALOG_REGISTRY.pop("tia_income", None)


@pytest.mark.asyncio
async def test_activate_endpoint(client: AsyncClient, db_session) -> None:
    proposal = TiaProposal(api_name="income", status="approved", data_type="tia_income")
    db_session.add(proposal)
    await db_session.commit()
    await db_session.refresh(proposal)
    from app.services.tia.override_service import TiaOverrideService

    override = TiaOverrideService().build_override_from_api("income")
    db_session.add(override)
    await db_session.commit()

    with patch("app.api.v1.endpoints.tia.run_tia_activate_task.delay"):
        response = await client.post(f"/api/v1/tia/proposals/{proposal.id}/activate")
    assert response.status_code == 200
    assert response.json()["job_id"] >= 1


@pytest.mark.asyncio
async def test_points_audit(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tia/audit")
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job_resp = await client.get(f"/api/v1/tia/scan/{job_id}")
    assert job_resp.json()["status"] == "success"


def test_cleanup_export_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    old = tmp_path / "export_old.csv"
    old.write_text("a,b", encoding="utf-8")
    import os
    import time

    os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    from app.tasks.maintenance_tasks import cleanup_export_files_task

    result = cleanup_export_files_task(max_age_days=30)
    assert result["deleted"] >= 1
    get_settings.cache_clear()
