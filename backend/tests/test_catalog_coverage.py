"""Catalog coverage API tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_catalog_coverage(client: AsyncClient) -> None:
    response = await client.get("/api/v1/catalog/coverage")
    assert response.status_code == 200
    data = response.json()
    summary = data["summary"]
    assert summary["local_count"] >= 0
    assert summary["official_count"] >= 4
    assert summary["unchanged_count"] >= 0
    assert 0 <= summary["coverage_pct"] <= 100
    assert summary["official_index_source"]
    assert "new_on_official_sample" in data
    assert "local_only_sample" in data
    assert "unchanged_sample" in data


@pytest.mark.asyncio
async def test_catalog_coverage_stock_a_scope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/catalog/coverage?index_scope=stock_a&index_source=bundled")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["official_index_scope"] == "stock_a"
