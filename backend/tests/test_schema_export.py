"""JSON Schema export tests."""

import pytest
from httpx import AsyncClient

from app.models.tia_proposal import TiaProposal
from app.services.catalog.schema_export import build_json_schema, build_openapi_document


def test_build_json_schema_income() -> None:
    schema = build_json_schema(
        api_name="income",
        data_type="tushare_income",
        label="利润表",
        table_name="tushare_income",
        provider_id="tushare",
        schema={
            "columns": [
                {"key": "stock_code", "label": "代码", "type": "string", "nullable": False},
                {"key": "end_date", "label": "报告期", "type": "date", "nullable": False},
                {"key": "revenue", "label": "营收", "type": "number", "nullable": True},
            ],
            "unique_keys": ["stock_code", "end_date"],
            "field_mappings": {"ts_code": "stock_code"},
        },
    )
    assert schema["$schema"].endswith("draft-07/schema#")
    assert schema["properties"]["stock_code"]["type"] == "string"
    assert schema["properties"]["end_date"]["format"] == "date"
    assert set(schema["required"]) == {"stock_code", "end_date"}
    assert schema["x-ninehub"]["api_name"] == "income"


@pytest.fixture
async def seed_income_proposal(db_session):
    db_session.add(TiaProposal(api_name="income", status="pending", reason="new_on_official"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_export_json_schema_by_api(client: AsyncClient, seed_income_proposal) -> None:
    response = await client.get("/api/v1/catalog/data-standards/income/export?format=json_schema")
    assert response.status_code == 200
    data = response.json()
    assert data["api_name"] == "income"
    assert data["format"] == "json_schema"
    assert data["json_schema"]["type"] == "object"
    assert "stock_code" in data["json_schema"]["properties"]


@pytest.mark.asyncio
async def test_export_json_schema_by_data_type(client: AsyncClient, seed_income_proposal) -> None:
    response = await client.get(
        "/api/v1/catalog/data-standards/by-data-type/tushare_income/export?format=json_schema"
    )
    assert response.status_code == 200
    assert response.json()["data_type"] == "tushare_income"


@pytest.mark.asyncio
async def test_export_openapi_by_api(client: AsyncClient, seed_income_proposal) -> None:
    response = await client.get("/api/v1/catalog/data-standards/income/export?format=openapi")
    assert response.status_code == 200
    data = response.json()
    assert data["format"] == "openapi"
    assert data["openapi"]["openapi"] == "3.0.3"
    assert "tushare_income" in data["openapi"]["components"]["schemas"]


@pytest.mark.asyncio
async def test_export_bundle_zip(client: AsyncClient, seed_income_proposal) -> None:
    response = await client.get("/api/v1/catalog/data-standards/export?format=zip_json_schema")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert any(n.startswith("schemas/") and n.endswith(".schema.json") for n in names)


@pytest.mark.asyncio
async def test_export_bundle_openapi_json(client: AsyncClient, seed_income_proposal) -> None:
    response = await client.get("/api/v1/catalog/data-standards/export?format=openapi")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    doc = response.json()
    assert doc["openapi"] == "3.0.3"
    assert doc["components"]["schemas"]


@pytest.mark.asyncio
async def test_quality_suggestions_by_data_type(client: AsyncClient, seed_income_proposal) -> None:
    response = await client.get(
        "/api/v1/catalog/data-standards/by-data-type/tushare_income/quality-suggestions"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["api_name"] == "income"
    if data["suggestions"]:
        assert "config_json" in data["suggestions"][0]


def test_build_openapi_document() -> None:
    entries = [
        {
            "api_name": "income",
            "data_type": "tushare_income",
            "label": "利润表",
            "json_schema": build_json_schema(
                api_name="income",
                data_type="tushare_income",
                label="利润表",
                table_name="tushare_income",
                provider_id="tushare",
                schema={"columns": [{"key": "stock_code", "type": "string"}], "unique_keys": ["stock_code"]},
            ),
        }
    ]
    doc = build_openapi_document(entries)
    assert "tushare_income" in doc["components"]["schemas"]
    assert doc["paths"]["/api/v1/catalog/data/{data_type}"]["get"]
