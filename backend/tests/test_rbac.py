"""RBAC and user management tests."""

import pytest
from httpx import AsyncClient

from catalog_test_support import TEST_DATA_TYPE


@pytest.mark.asyncio
async def test_admin_list_users(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/users")
    assert response.status_code == 200
    assert response.json()["total"] >= 1


@pytest.mark.asyncio
async def test_disable_user(client: AsyncClient, normal_user) -> None:
    response = await client.patch(
        f"/api/v1/auth/users/{normal_user.id}",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_normal_cannot_list_users(normal_client: AsyncClient) -> None:
    response = await normal_client.get("/api/v1/auth/users")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_normal_cannot_create_task(normal_client: AsyncClient) -> None:
    response = await normal_client.post(
        "/api/v1/tasks",
        json={"data_type": TEST_DATA_TYPE},
    )
    assert response.status_code == 403
