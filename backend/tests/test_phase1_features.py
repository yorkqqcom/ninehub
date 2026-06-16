"""Task run API tests."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.schemas.task import SyncTaskCreate
from app.services.tasks.service import TaskService
from catalog_test_support import TEST_DATA_TYPE


@pytest.mark.asyncio
async def test_task_run_trigger(client: AsyncClient, db_session) -> None:
    service = TaskService()
    task = await service.create_task(
        db_session,
        SyncTaskCreate(data_type=TEST_DATA_TYPE, status="active"),
    )
    await db_session.commit()

    with patch("app.tasks.sync_tasks.run_collect") as mock_task:
        response = await client.post(f"/api/v1/tasks/{task.id}/run")
        assert response.status_code == 200
        body = response.json()
        assert "run_id" in body
        mock_task.delay.assert_called_once()

    runs_resp = await client.get(f"/api/v1/tasks/{task.id}/runs")
    assert runs_resp.status_code == 200
    assert runs_resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_auth_me(client: AsyncClient, admin_user) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
