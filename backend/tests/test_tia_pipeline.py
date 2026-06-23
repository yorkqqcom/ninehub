"""TIA L3 pipeline tests — schema, migration, activation, browse."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.catalog.registry import CATALOG_REGISTRY, get_data_type_entry
from app.models.base import Base
from app.models.platform_job import PlatformJob
from app.models.quality import QualityRule
from app.models.tia_proposal import TiaProposal
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import ACTIVATION_STEPS, TiaActivationService
from app.services.tia.migration_service import TiaMigrationService
from app.services.tia.schema_inference import infer_schema_for_api, infer_unique_keys
from app.services.tia.scaffold_service import TiaScaffoldService
from app.services.tia.override_service import TiaOverrideService
from app.services.tia.preflight_test_service import PreflightTestResult, TiaPreflightTestService

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


def test_infer_schema_income() -> None:
    schema = infer_schema_for_api("income")
    keys = [c["key"] for c in schema["columns"]]
    assert "stock_code" in keys
    assert schema["unique_keys"] == ["stock_code", "end_date"]
    assert schema["field_mappings"]["ts_code"] == "stock_code"


def test_migration_creates_table() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    schema = infer_schema_for_api("income")
    created = TiaMigrationService().ensure_table(session, "tia_income_test", schema)
    assert created is True
    created_again = TiaMigrationService().ensure_table(session, "tia_income_test", schema)
    assert created_again is False
    session.close()


def test_l3_six_step_activation() -> None:
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

    override = TiaOverrideService().build_override_from_api("income")
    override.table_name = "tia_income"
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
    for step in ACTIVATION_STEPS:
        assert result["steps"][step]["status"] == "success"

    entry = get_data_type_entry("tia_income")
    assert entry is not None
    assert entry.browse_enabled is False
    assert entry.is_activated is True
    col_keys = [c.key for c in entry.columns]
    assert "stock_code" in col_keys
    assert len(col_keys) == len(INCOME_LIVE_FIELDS)

    oj = override.override_json or {}
    assert oj["schema"]["field_mappings"]["ts_code"] == "stock_code"

    rules = session.query(QualityRule).filter(QualityRule.target_data_type == "tia_income").all()
    assert len(rules) >= 1

    updated = session.get(TiaProposal, proposal.id)
    assert updated.status == "applied"

    session.close()
    CATALOG_REGISTRY.pop("tia_income", None)


@pytest.mark.asyncio
async def test_enable_browse(client: AsyncClient, db_session) -> None:
    proposal = TiaProposal(
        api_name="income",
        status="applied",
        data_type="tia_income",
    )
    db_session.add(proposal)
    override = TiaOverrideService().build_override_from_api("income")
    override.is_activated = True
    override.table_name = "tia_income"
    db_session.add(override)
    await db_session.commit()
    await db_session.refresh(proposal)

    response = await client.post(f"/api/v1/tia/proposals/{proposal.id}/enable-browse")
    assert response.status_code == 200
    assert response.json()["browse_enabled"] is True


@pytest.mark.asyncio
async def test_approve_activate_endpoint(client: AsyncClient, db_session) -> None:
    proposal = TiaProposal(api_name="income", status="pending", action="review")
    db_session.add(proposal)
    await db_session.commit()
    await db_session.refresh(proposal)

    from unittest.mock import MagicMock, patch

    mock_preflight = MagicMock(passed=True, blocking_errors=[])
    mock_preflight.to_activation_step.return_value = {"status": "success", "passed": True}

    with patch("app.api.v1.endpoints.tia.dispatch_tia_activate_jobs"), patch(
        "app.api.v1.endpoints.tia._run_preflight_sync", return_value=mock_preflight
    ):
        response = await client.post(f"/api/v1/tia/proposals/{proposal.id}/approve-activate")
    assert response.status_code == 200
    assert response.json()["job_id"] >= 1


@pytest.mark.asyncio
async def test_batch_review(client: AsyncClient, db_session) -> None:
    p1 = TiaProposal(api_name="income", status="pending")
    p2 = TiaProposal(api_name="balancesheet", status="pending")
    db_session.add_all([p1, p2])
    await db_session.commit()
    await db_session.refresh(p1)
    await db_session.refresh(p2)

    response = await client.post(
        "/api/v1/tia/proposals/batch-review",
        json={"proposal_ids": [p1.id, p2.id], "status": "approved", "note": "batch"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["status"] == "approved"


@pytest.mark.asyncio
async def test_batch_approve_activate(client: AsyncClient, db_session) -> None:
    from unittest.mock import MagicMock, patch

    p1 = TiaProposal(api_name="income", status="pending")
    p2 = TiaProposal(api_name="daily", status="pending")
    db_session.add_all([p1, p2])
    await db_session.commit()
    await db_session.refresh(p1)
    await db_session.refresh(p2)

    mock_preflight = MagicMock(passed=True, blocking_errors=[])
    mock_preflight.to_activation_step.return_value = {"status": "success", "passed": True}

    with patch("app.api.v1.endpoints.tia._run_preflight_sync", return_value=mock_preflight), patch(
        "app.api.v1.endpoints.tia.dispatch_tia_activate_jobs"
    ) as mock_dispatch:
        response = await client.post(
            "/api/v1/tia/proposals/batch-approve-activate",
            json={"proposal_ids": [p1.id, p2.id], "note": "batch activate"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert len(body["job_ids"]) == 2
    mock_dispatch.assert_called_once()
    assert len(mock_dispatch.call_args[0][0]) == 2


@pytest.mark.asyncio
async def test_batch_activate_approved(client: AsyncClient, db_session) -> None:
    from unittest.mock import patch

    from app.services.tia.override_service import TiaOverrideService

    p1 = TiaProposal(api_name="income", status="approved", data_type="tushare_income")
    p2 = TiaProposal(api_name="daily", status="failed", data_type="tushare_daily")
    db_session.add_all([p1, p2])
    for api in ("income", "daily"):
        ov = TiaOverrideService().build_override_from_api(api)
        db_session.add(ov)
    await db_session.commit()
    await db_session.refresh(p1)
    await db_session.refresh(p2)

    with patch("app.api.v1.endpoints.tia.dispatch_tia_activate_jobs") as mock_dispatch:
        response = await client.post(
            "/api/v1/tia/proposals/batch-activate",
            json={"proposal_ids": [p1.id, p2.id]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert len(body["job_ids"]) == 2
    mock_dispatch.assert_called_once()
    assert len(mock_dispatch.call_args[0][0]) == 2


@pytest.mark.asyncio
async def test_batch_activate_rejects_pending(client: AsyncClient, db_session) -> None:
    p = TiaProposal(api_name="income", status="pending")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    with patch("app.api.v1.endpoints.tia.dispatch_tia_activate_jobs"):
        response = await client.post(
            "/api/v1/tia/proposals/batch-activate",
            json={"proposal_ids": [p.id]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 0
    assert body["failed"] == 1


@pytest.mark.asyncio
async def test_batch_enable_browse(client: AsyncClient, db_session) -> None:
    p1 = TiaProposal(api_name="income", status="applied", data_type="tia_income")
    p2 = TiaProposal(api_name="daily", status="pending")
    db_session.add_all([p1, p2])
    override = TiaOverrideService().build_override_from_api("income")
    override.is_activated = True
    db_session.add(override)
    await db_session.commit()
    await db_session.refresh(p1)
    await db_session.refresh(p2)

    response = await client.post(
        "/api/v1/tia/proposals/batch-enable-browse",
        json={"proposal_ids": [p1.id, p2.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["items"][0]["browse_enabled"] is True


@pytest.mark.asyncio
async def test_browse_data_after_activation(client: AsyncClient, db_session) -> None:
    from app.catalog.registry import register_catalog_entry, DataTypeEntry, CATALOG_REGISTRY
    from app.schemas.catalog import CatalogColumnMeta

    register_catalog_entry(
        DataTypeEntry(
            data_type="tia_test_browse",
            domain="financial",
            label="测试浏览",
            table_name="tia_test_browse",
            is_activated=True,
            browse_enabled=True,
            columns=[
                CatalogColumnMeta(key="ts_code", label="代码", type="string"),
                CatalogColumnMeta(key="value", label="值", type="number"),
            ],
        )
    )
    await db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS tia_test_browse "
            "(id INTEGER PRIMARY KEY, ts_code VARCHAR(32), value NUMERIC)"
        )
    )
    await db_session.execute(
        text("INSERT INTO tia_test_browse (ts_code, value) VALUES ('000001.SZ', 1.5)")
    )
    await db_session.commit()

    response = await client.get("/api/v1/catalog/data/tia_test_browse?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["items"][0]["ts_code"] == "000001.SZ"
    CATALOG_REGISTRY.pop("tia_test_browse", None)


def test_scaffold_still_builds() -> None:
    override = TiaOverrideService().build_override_from_api("income")
    content = TiaScaffoldService().build_zip(override)
    assert content[:2] == b"PK"
