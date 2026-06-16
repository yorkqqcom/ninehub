"""Tests for F-08 points audit."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_points_audit_override_vs_sidebar(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tia/audit")
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    job_resp = await client.get(f"/api/v1/tia/scan/{job_id}")
    assert job_resp.status_code == 200
    job = job_resp.json()
    assert job["status"] == "success"
    result = job["result"]
    assert "doc14_gaps" in result
    assert "points_mismatches" in result
    assert result["sources"] == ["document2_sidebar", "doc_pages_cache", "tia_overrides"]
    assert "doc108_summary" in result.get("deprecated_sources", [])
