"""Platform settings API tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_settings_default(client: AsyncClient) -> None:
    response = await client.get("/api/v1/platform/settings")
    assert response.status_code == 200
    data = response.json()
    assert "sync_start_date" in data
    assert "sync_type_overrides" in data


@pytest.mark.asyncio
async def test_update_settings(client: AsyncClient) -> None:
    response = await client.put(
        "/api/v1/platform/settings",
        json={"sync_start_date": "2015-01-01", "sync_type_overrides": {"tia_income": "2018-01-01"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sync_start_date"] == "2015-01-01"
    assert data["sync_type_overrides"]["tia_income"] == "2018-01-01"


@pytest.mark.asyncio
async def test_normal_user_cannot_access_settings(normal_client: AsyncClient) -> None:
    response = await normal_client.get("/api/v1/platform/settings")
    assert response.status_code == 403
