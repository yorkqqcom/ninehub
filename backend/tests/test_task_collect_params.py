"""Tests for per-task collect param overrides."""

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.models.sync_task import SyncTask
from app.services.tasks.collect_config_service import (
    build_collect_config,
    normalize_task_collect_params,
    validate_task_collect_params_for_api,
)
from app.sync.tia_collect.params import resolve_collect_params
from catalog_test_support import TEST_DATA_TYPE


def test_normalize_strips_probe_keys() -> None:
    assert normalize_task_collect_params({"limit": 3}) == {}
    assert normalize_task_collect_params({"exchange": "SSE", "fields": "a,b"}) == {
        "exchange": "SSE"
    }


def test_stock_basic_task_override_merge() -> None:
    default = resolve_collect_params("stock_basic", {})
    effective = resolve_collect_params(
        "stock_basic",
        {},
        exchange="",
        list_status="L",
        market="主板",
    )
    assert default.get("exchange") == ""
    assert effective.get("market") == "主板"


def test_build_collect_config_runtime_keys() -> None:
    cfg = build_collect_config(
        api_name="daily",
        schema={"collect": {"mode": "date_range"}},
        task_overrides=None,
    )
    assert cfg["collect_mode"] == "date_range"
    assert "ts_code" in cfg["runtime_keys"]


def test_validate_blocks_runtime_key() -> None:
    with pytest.raises(Exception):
        validate_task_collect_params_for_api(
            "daily",
            {},
            {"ts_code": "000001.SZ"},
        )


@pytest.mark.asyncio
async def test_collect_config_endpoint(client: AsyncClient, db_session) -> None:
    create = await client.post(
        "/api/v1/tasks",
        json={"data_type": TEST_DATA_TYPE, "status": "active"},
    )
    assert create.status_code == 200
    task_id = create.json()["id"]

    config = await client.get(f"/api/v1/tasks/{task_id}/collect-config")
    assert config.status_code == 200
    body = config.json()
    assert body["task_id"] == task_id
    assert "default_params" in body
    assert "effective_params" in body


@pytest.mark.asyncio
async def test_update_collect_params(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/tasks",
        json={"data_type": TEST_DATA_TYPE, "status": "active"},
    )
    task_id = create.json()["id"]

    updated = await client.put(
        f"/api/v1/tasks/{task_id}",
        json={"collect_params": {"exchange": "SZSE"}},
    )
    assert updated.status_code == 200
    assert updated.json()["collect_params"] == {"exchange": "SZSE"}

    cleared = await client.put(
        f"/api/v1/tasks/{task_id}",
        json={"collect_params": {}},
    )
    assert cleared.status_code == 200
    assert cleared.json()["collect_params"] == {}
