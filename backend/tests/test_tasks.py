"""Task and catalog API tests."""

import pytest
from httpx import AsyncClient

from app.core.exceptions import ValidationError
from app.schemas.task import SyncTaskCreate
from app.services.tasks.service import TaskService
from catalog_test_support import TEST_DATA_TYPE, TEST_DATA_TYPE_LABEL


@pytest.mark.asyncio
async def test_catalog_data_types(client: AsyncClient) -> None:
    response = await client.get("/api/v1/catalog/data-types")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 1
    assert len(data["domains"]) == 7
    types = {item["data_type"] for item in data["items"]}
    assert TEST_DATA_TYPE in types


@pytest.mark.asyncio
async def test_tasks_data_types_alias(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/data-types")
    assert response.status_code == 200
    assert len(response.json()["items"]) >= 1


@pytest.mark.asyncio
async def test_create_task_with_catalog_type(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"name": "利润表同步", "data_type": TEST_DATA_TYPE, "status": "active"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data_type"] == TEST_DATA_TYPE
    assert body["data_type_label"] == TEST_DATA_TYPE_LABEL


@pytest.mark.asyncio
async def test_create_task_invalid_data_type(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"data_type": "not_in_catalog"},
    )
    assert response.status_code == 400
    assert "catalog" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/tasks",
        json={"data_type": TEST_DATA_TYPE, "status": "paused"},
    )
    response = await client.get("/api/v1/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert data["items"][0]["data_type_label"] == TEST_DATA_TYPE_LABEL


@pytest.mark.asyncio
async def test_task_service_validation(db_session) -> None:
    service = TaskService()
    with pytest.raises(ValidationError):
        await service.create_task(db_session, SyncTaskCreate(data_type="invalid_type"))
