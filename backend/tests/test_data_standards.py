"""Data standard mapping checklist tests."""

import pytest
from httpx import AsyncClient

from app.models.tia_proposal import TiaProposal


@pytest.fixture
async def seed_standard_proposals(db_session):
    for api in ("daily", "stock_basic", "income", "top_inst", "share_float"):
        db_session.add(TiaProposal(api_name=api, status="pending", reason="new_on_official"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_data_standards_list_from_proposals(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 5
    assert data["summary"]["proposal_total"] >= 5
    assert data["summary"]["configured_count"] >= 0
    assert "template_count" in data["summary"]
    assert "unconfigured_count" in data["summary"]
    names = {i["api_name"] for i in data["items"]}
    assert "income" in names
    assert "stock_basic" in names
    assert all("proposal_id" in i and "schema_stage" in i and "field_source" in i for i in data["items"])
    income = next(i for i in data["items"] if i["api_name"] == "income")
    assert income["schema_stage"] in ("schema_ready", "schema_preview", "schema_persisted", "activated")
    assert income["field_source"] in ("catalog_probe", "template")


@pytest.mark.asyncio
async def test_data_standards_filter_proposal_status(client: AsyncClient, db_session) -> None:
    db_session.add(TiaProposal(api_name="balancesheet", status="pending", reason="new_on_official"))
    await db_session.commit()

    response = await client.get("/api/v1/catalog/data-standards?proposal_status=pending&q=balancesheet")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["api_name"] == "balancesheet"
    assert item["proposal_status"] == "pending"
    assert item["probe_status"] == "configured"


@pytest.mark.asyncio
async def test_data_standards_detail(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards/income")
    assert response.status_code == 200
    data = response.json()
    assert data["api_name"] == "income"
    assert len(data["fields"]) >= 1
    assert data["field_mappings"]["ts_code"] == "stock_code"
    assert data["ddl_ready"] is True
    assert data["unique_keys"] == ["stock_code", "end_date"]
    assert data["doc_id"] is not None
    assert data["proposal_id"] > 0


@pytest.mark.asyncio
async def test_data_standards_detail_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/catalog/data-standards/nonexistent_api_xyz")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_data_standards_search(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards?q=daily")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert all("daily" in i["api_name"].lower() or "daily" in i["label"].lower() for i in data["items"])


@pytest.mark.asyncio
async def test_data_standards_filter_by_api(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards?api=income")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["api_name"] == "income"


@pytest.mark.asyncio
async def test_data_standards_naming_compliance_fields(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards/income")
    assert response.status_code == 200
    data = response.json()
    assert data["provider_id"] == "tushare"
    assert data["table_name"]
    assert "score" in data["naming_compliance"]
    assert isinstance(data["naming_compliance"]["issues"], list)


@pytest.mark.asyncio
async def test_data_standards_drift_endpoint(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards/income/drift")
    assert response.status_code == 200
    data = response.json()
    assert data["api_name"] == "income"
    assert data["drift_status"] in ("none", "doc_drift", "live_drift", "ddl_drift")
    assert "doc_drift" in data
    assert "live_drift" in data


@pytest.mark.asyncio
async def test_data_standards_quality_suggestions(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards/income/quality-suggestions")
    assert response.status_code == 200
    data = response.json()
    assert data["api_name"] == "income"
    assert isinstance(data["suggestions"], list)
    if data["suggestions"]:
        assert data["suggestions"][0]["rule_type"] == "no_nulls"


@pytest.mark.asyncio
async def test_data_standards_summary_drift_count(client: AsyncClient, seed_standard_proposals) -> None:
    response = await client.get("/api/v1/catalog/data-standards")
    assert response.status_code == 200
    assert "drift_count" in response.json()["summary"]


@pytest.mark.asyncio
async def test_data_standards_probe_status_filter(client: AsyncClient) -> None:
    response = await client.get("/api/v1/catalog/data-standards?probe_status=configured")
    assert response.status_code == 200
    assert all(i["probe_status"] == "configured" for i in response.json()["items"])
