"""Quality API tests."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.quality.service import resolve_no_null_fields
from app.models.quality import QualityRule
from catalog_test_support import TEST_DATA_TYPE


def test_resolve_no_null_fields_prefers_fields() -> None:
    rule = QualityRule(
        name="x",
        rule_type="no_nulls",
        target_data_type=TEST_DATA_TYPE,
        config_json={"fields": ["end_date"]},
    )
    assert resolve_no_null_fields(rule) == ["end_date"]


def test_resolve_no_null_fields_legacy_column() -> None:
    rule = QualityRule(
        name="x",
        rule_type="no_nulls",
        target_data_type=TEST_DATA_TYPE,
        config_json={"column": "stock_code"},
    )
    assert resolve_no_null_fields(rule) == ["stock_code"]


def test_resolve_no_null_fields_falls_back_to_catalog() -> None:
    rule = QualityRule(
        name="x",
        rule_type="no_nulls",
        target_data_type=TEST_DATA_TYPE,
        config_json={},
    )
    assert resolve_no_null_fields(rule) == ["stock_code", "end_date"]


@pytest.mark.asyncio
async def test_no_nulls_legacy_column_config(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "end_date not null",
            "rule_type": "no_nulls",
            "target_data_type": TEST_DATA_TYPE,
            "config_json": {"column": "end_date"},
        },
    )
    with patch(
        "app.services.quality.service.CatalogQueryService.count_nulls",
        new_callable=AsyncMock,
        return_value={"end_date": 1},
    ):
        run_resp = await client.post("/api/v1/quality/run", json={"data_type": TEST_DATA_TYPE})
    assert run_resp.status_code == 200
    reports = await client.get(
        f"/api/v1/quality/reports?data_type={TEST_DATA_TYPE}&status=failed"
    )
    assert reports.json()["total"] >= 1
    assert reports.json()["items"][0]["detail_json"]["null_counts"] == {"end_date": 1}


@pytest.mark.asyncio
async def test_toggle_rule_enabled(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "toggle me",
            "rule_type": "min_rows",
            "threshold": 0,
            "target_data_type": TEST_DATA_TYPE,
            "is_enabled": True,
        },
    )
    rule_id = create.json()["id"]
    patch_resp = await client.patch(
        f"/api/v1/quality/rules/{rule_id}",
        json={"is_enabled": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_enabled"] is False


@pytest.mark.asyncio
async def test_create_rule_and_run(client: AsyncClient) -> None:
    rule_resp = await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "最少行数",
            "rule_type": "min_rows",
            "threshold": 0,
            "target_data_type": TEST_DATA_TYPE,
        },
    )
    assert rule_resp.status_code == 200

    run_resp = await client.post("/api/v1/quality/run", json={"data_type": TEST_DATA_TYPE})
    assert run_resp.status_code == 200
    assert run_resp.json()["reports_created"] >= 1

    reports = await client.get(f"/api/v1/quality/reports?data_type={TEST_DATA_TYPE}")
    assert reports.status_code == 200
    assert reports.json()["total"] >= 1


@pytest.mark.asyncio
async def test_disabled_rule_skipped(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "禁用规则",
            "rule_type": "min_rows",
            "threshold": 999999,
            "target_data_type": TEST_DATA_TYPE,
            "is_enabled": False,
        },
    )
    assert create.status_code == 200
    run_resp = await client.post("/api/v1/quality/run", json={"data_type": TEST_DATA_TYPE})
    assert run_resp.json()["reports_created"] == 0


@pytest.mark.asyncio
async def test_invalid_data_type_rule(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "Bad",
            "rule_type": "min_rows",
            "threshold": 1,
            "target_data_type": "not_in_catalog",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_normal_user_can_read_reports(normal_client: AsyncClient) -> None:
    response = await normal_client.get("/api/v1/quality/reports")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reports_pagination(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "page rule",
            "rule_type": "min_rows",
            "threshold": 0,
            "target_data_type": TEST_DATA_TYPE,
        },
    )
    await client.post("/api/v1/quality/run", json={"data_type": TEST_DATA_TYPE})
    page1 = await client.get(f"/api/v1/quality/reports?data_type={TEST_DATA_TYPE}&skip=0&limit=1")
    assert page1.status_code == 200
    body = page1.json()
    assert body["total"] >= 1
    assert len(body["items"]) == 1
    assert body["page"] == 1
    assert body["size"] == 1


@pytest.mark.asyncio
async def test_run_with_stock_code(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/quality/rules",
        json={
            "name": "scoped min rows",
            "rule_type": "min_rows",
            "threshold": 0,
            "target_data_type": TEST_DATA_TYPE,
        },
    )
    with patch(
        "app.services.quality.service.CatalogQueryService.count_rows",
        new_callable=AsyncMock,
        return_value=5,
    ) as mock_count:
        run_resp = await client.post(
            "/api/v1/quality/run",
            json={"data_type": TEST_DATA_TYPE, "stock_code": "000001.SZ"},
        )
    assert run_resp.status_code == 200
    mock_count.assert_awaited()
    assert mock_count.await_args.args[2] == {"stock_code": "000001.SZ"}


@pytest.mark.asyncio
async def test_normal_user_cannot_run_quality(normal_client: AsyncClient) -> None:
    response = await normal_client.post("/api/v1/quality/run", json={})
    assert response.status_code == 403
