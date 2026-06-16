"""TIA scan and platform_jobs progress tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.platform_job import PlatformJob
from app.models.tia_override import TiaOverride
from app.services.platform.job_service import PlatformJobService
from app.services.tia.service import TIAService
from app.services.tia.api_probe_service import TiaApiProbeService
from app.services.tia.scan.types import ScanOptions


def test_tia_scan_skips_proposal_when_override_exists() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        TiaOverride(
            api_name="balancesheet",
            data_type="tia_balancesheet",
            label="Balancesheet",
            min_points=600,
        )
    )
    session.commit()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()
    result = TIAService().execute_scan_sync(
        session, job.id, ScanOptions(probe=False, mode="full", index_source="bundled", index_scope="mixed")
    )
    assert "balancesheet" not in result["new_on_official"]
    assert "balancesheet" in result["unchanged"]
    assert result["proposals_created"] >= 0
    session.close()


@pytest.mark.asyncio
async def test_tia_scan_endpoint_accepts_probe_unlimited(client: AsyncClient) -> None:
    from unittest.mock import patch

    with patch("app.api.v1.endpoints.tia.dispatch_task") as mock_dispatch:
        response = await client.post(
            "/api/v1/tia/scan",
            json={
                "mode": "full",
                "probe_scope": "all",
                "probe_unlimited": True,
            },
        )
        assert response.status_code == 200
        scan_opts = mock_dispatch.call_args[0][2]
        assert scan_opts["probe_unlimited"] is True


@pytest.mark.asyncio
async def test_tia_scan_endpoint_accepts_probe_limit(client: AsyncClient, db_session) -> None:
    from unittest.mock import patch

    with patch("app.api.v1.endpoints.tia.dispatch_task") as mock_dispatch:
        response = await client.post(
            "/api/v1/tia/scan",
            json={
                "mode": "full",
                "probe_limit": 200,
                "probe_scope": "all",
            },
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        assert mock_dispatch.call_args[0][1] == job_id
        scan_opts = mock_dispatch.call_args[0][2]
        assert scan_opts["probe_limit"] == 200

    job = await db_session.get(PlatformJob, job_id)
    assert job.result_json["scan_options"]["probe_limit"] == 200


@pytest.mark.asyncio
async def test_tia_scan_endpoint_queues_job(client: AsyncClient, db_session) -> None:
    from unittest.mock import patch

    with patch("app.api.v1.endpoints.tia.dispatch_task") as mock_dispatch:
        response = await client.post("/api/v1/tia/scan")
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        mock_dispatch.assert_called_once()
        assert mock_dispatch.call_args[0][1] == job_id

    job = await db_session.get(PlatformJob, job_id)
    assert job is not None
    assert job.job_type == "tia_scan"
    assert job.status == "pending"


def test_tia_scan_updates_progress_sync() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    job_service = PlatformJobService()
    job = job_service.create_sync(session, "tia_scan")
    session.commit()

    service = TIAService()
    result = service.execute_scan_sync(
        session,
        job.id,
        ScanOptions(probe=False, mode="full", index_source="bundled", index_scope="mixed"),
    )

    assert result["local_count"] == 0
    assert result["official_count"] >= 54
    assert len(result["new_on_official"]) >= 54
    assert result["local_override_count"] == 0
    assert result["missing_from_official"] == []
    assert "api_probes" in result
    assert result["api_probes"] == []
    assert result["probe_planner"]["planned"] == 0

    updated = session.get(PlatformJob, job.id)
    assert updated.status == "success"
    assert updated.progress == 100
    assert updated.result_json is not None
    session.close()


def test_tia_scan_runs_api_probes_with_token() -> None:
    from unittest.mock import patch

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    def fake_probe(self, api_names, *, token, account_points, max_calls_per_minute=None, official_map=None, override_points=None, on_progress=None):
        assert token == "fake-token"
        rows = [
            {
                "api": api,
                "status": "ok",
                "rows": 1,
                "doc_consistent": True,
                "missing_fields": [],
                "message": "ok",
            }
            for api in api_names
        ]
        if on_progress:
            for idx, row in enumerate(rows, start=1):
                on_progress(row["api"], row, idx, len(rows))
        return rows

    with patch(
        "app.services.tia.scan.adapters.tushare.resolve_tushare_scan_credentials",
        return_value={"token": "fake-token", "account_points": 5000, "source_id": 1},
    ), patch.object(TiaApiProbeService, "probe_catalog_apis", fake_probe):
        result = TIAService().execute_scan_sync(session, job.id, ScanOptions(probe=True))

    assert result["api_probe_summary"]["ok"] >= 5
    assert len(result["api_probes"]) >= 5
    session.close()


@pytest.mark.asyncio
async def test_tia_scan_job_status_api(client: AsyncClient, db_session) -> None:
    job = PlatformJob(
        job_type="tia_scan",
        status="success",
        progress=100,
        message="done",
        result_json={"new_on_official": ["income"]},
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    response = await client.get(f"/api/v1/tia/scan/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["progress"] == 100
    assert data["result"]["new_on_official"] == ["income"]
