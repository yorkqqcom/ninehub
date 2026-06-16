"""Phase 3 feature tests: quality alerts, akshare."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.quality import QualityReport, QualityRule
from app.services.quality.alert_service import QualityAlertService
from app.services.quality.service import QualityService
from catalog_test_support import TEST_DATA_TYPE


@pytest.mark.asyncio
async def test_quality_async_mode(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "async rule",
            "rule_type": "min_rows",
            "threshold": 0,
            "target_data_type": TEST_DATA_TYPE,
        },
    )
    with patch("app.api.v1.endpoints.quality.run_quality_check_task.delay"):
        response = await client.post(
            "/api/v1/quality/run",
            json={"data_type": TEST_DATA_TYPE, "async_mode": True},
        )
    assert response.status_code == 200
    assert response.json()["job_id"] >= 1


def test_quality_alert_service_logs_failed() -> None:
    report = QualityReport(data_type=TEST_DATA_TYPE, status="failed", detail_json={"x": 1})
    sent = QualityAlertService().notify_failed_reports([report])
    assert sent == 1


def test_quality_run_check_sync() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        QualityRule(
            name="min",
            rule_type="min_rows",
            threshold=0,
            target_data_type=TEST_DATA_TYPE,
            is_enabled=True,
        )
    )
    session.commit()
    service = QualityService()
    result = service.run_check_sync(session, data_type=TEST_DATA_TYPE)
    session.commit()
    assert result.reports_created == 1
    session.close()


@pytest.mark.asyncio
async def test_verify_akshare_provider(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources/verify",
        json={"provider": "akshare"},
    )
    assert response.status_code == 200
    assert "AkShare" in response.json()["message"]


def test_akshare_collector_registered() -> None:
    import app.services.collectors  # noqa: F401
    from app.services.collectors.manager import CollectorManager

    collector = CollectorManager.get("akshare")
    assert collector.source_type == "akshare"


def test_tushare_collector_registered() -> None:
    import app.services.collectors  # noqa: F401
    from app.services.collectors.manager import CollectorManager

    collector = CollectorManager.get("tushare")
    assert collector.source_type == "tushare"
