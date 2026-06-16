"""Data source API tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_sources_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/sources")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_create_and_mask_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources",
        json={
            "name": "Tushare 主账号",
            "provider": "tushare",
            "config": {"token": "abcd1234efgh5678", "account_points": 120},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["token"] == "abcd****5678"
    assert body["config"]["account_points"] == 120
    assert "efgh" not in body["config"]["token"]


@pytest.mark.asyncio
async def test_create_tushare_requires_account_points(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources",
        json={"name": "No points", "provider": "tushare", "config": {}},
    )
    assert response.status_code == 400
    assert "account_points" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_akshare_ok(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources",
        json={"name": "AkShare", "provider": "akshare", "config": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "akshare"
    assert body.get("quota") is None


@pytest.mark.asyncio
async def test_create_akshare_strips_tushare_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources",
        json={
            "name": "AkShare",
            "provider": "akshare",
            "config": {"account_points": 2000, "max_calls_per_minute": 100},
        },
    )
    assert response.status_code == 200
    assert "account_points" not in response.json()["config"]


@pytest.mark.asyncio
async def test_create_empty_name_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources",
        json={"name": "", "provider": "tushare", "config": {"account_points": 120}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_source_keep_token(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/sources",
        json={
            "name": "Src",
            "provider": "tushare",
            "config": {"token": "secret12345678", "account_points": 120},
        },
    )
    source_id = create.json()["id"]
    response = await client.put(
        f"/api/v1/sources/{source_id}",
        json={"name": "Renamed", "config": {"token": ""}},
    )
    assert response.status_code == 200
    get_resp = await client.get(f"/api/v1/sources/{source_id}")
    assert "secr****5678" in get_resp.json()["config"]["token"]


@pytest.mark.asyncio
async def test_create_tushare_with_account_points(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources",
        json={
            "name": "Tushare 2000",
            "provider": "tushare",
            "config": {"token": "abcd1234efgh5678", "account_points": 2000},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quota"]["account_points"] == 2000
    assert body["quota"]["max_calls_per_minute"] == 200
    assert body["quota"]["account_points_from_source"] is True


@pytest.mark.asyncio
async def test_update_account_points(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/sources",
        json={"name": "Src", "provider": "tushare", "config": {"account_points": 120}},
    )
    source_id = create.json()["id"]
    response = await client.put(
        f"/api/v1/sources/{source_id}",
        json={"config": {"account_points": 5000}},
    )
    assert response.status_code == 200
    assert response.json()["quota"]["max_calls_per_minute"] == 500


@pytest.mark.asyncio
async def test_normal_user_can_read_sources(normal_client: AsyncClient) -> None:
    response = await normal_client.get("/api/v1/sources")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_normal_user_cannot_create_source(normal_client: AsyncClient) -> None:
    response = await normal_client.post(
        "/api/v1/sources",
        json={"name": "X", "provider": "tushare", "config": {"account_points": 120}},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_switch_to_akshare_strips_quota(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/sources",
        json={
            "name": "Switch",
            "provider": "tushare",
            "config": {"account_points": 2000},
        },
    )
    source_id = create.json()["id"]
    response = await client.put(
        f"/api/v1/sources/{source_id}",
        json={"provider": "akshare"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "akshare"
    assert "account_points" not in body["config"]
    assert body.get("quota") is None


@pytest.mark.asyncio
async def test_verify_without_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sources/verify",
        json={"provider": "tushare"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
