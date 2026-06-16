"""Catalog browse API tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.catalog.registry import CATALOG_REGISTRY, DataTypeEntry, register_catalog_entry
from app.schemas.catalog import CatalogColumnMeta, CatalogFilterMeta
from app.services.tia.override_service import TiaOverrideService
from app.models.tia_override import TiaOverride


@pytest.mark.asyncio
async def test_browse_only_single_entry_per_activated_api(client: AsyncClient) -> None:
    """Canonical + legacy alias must not both appear in browse list (e.g. trade_cal)."""
    override = TiaOverride(
        api_name="trade_cal",
        data_type="tushare_trade_cal",
        domain="basic",
        label="trade_cal",
        min_points=0,
        table_name="tushare_trade_cal",
        is_activated=True,
        override_json={
            "browse_enabled": True,
            "schema": {
                "columns": [
                    {"key": "exchange", "label": "交易所", "type": "string"},
                    {"key": "cal_date", "label": "日期", "type": "date"},
                ],
                "unique_keys": ["exchange", "cal_date"],
            },
        },
    )
    TiaOverrideService().apply_to_registry(override, browse_enabled=True)
    try:
        response = await client.get("/api/v1/catalog/data-types?browse_only=true")
        assert response.status_code == 200
        body = response.json()
        trade_items = [i for i in body["items"] if "trade_cal" in i["data_type"]]
        assert len(trade_items) == 1
        assert trade_items[0]["data_type"] == "tushare_trade_cal"
        assert body["summary"]["total"] == len(body["items"])
    finally:
        CATALOG_REGISTRY.pop("tushare_trade_cal", None)
        CATALOG_REGISTRY.pop("tia_trade_cal", None)


@pytest.mark.asyncio
async def test_browse_data_types_browse_only(client: AsyncClient) -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type="browse_test_on",
            domain="market",
            label="可浏览",
            table_name="browse_test_on",
            is_activated=True,
            browse_enabled=True,
            columns=[CatalogColumnMeta(key="ts_code", label="代码", type="string")],
        )
    )
    register_catalog_entry(
        DataTypeEntry(
            data_type="browse_test_off",
            domain="market",
            label="不可浏览",
            table_name="browse_test_off",
            is_activated=True,
            browse_enabled=False,
            columns=[CatalogColumnMeta(key="ts_code", label="代码", type="string")],
        )
    )
    try:
        response = await client.get("/api/v1/catalog/data-types?browse_only=true")
        assert response.status_code == 200
        body = response.json()
        types = {i["data_type"] for i in body["items"]}
        assert "browse_test_on" in types
        assert "browse_test_off" not in types
        assert body["summary"]["total"] >= 1
        assert any(d["domain"] == "market" for d in body["summary"]["domains"])
    finally:
        CATALOG_REGISTRY.pop("browse_test_on", None)
        CATALOG_REGISTRY.pop("browse_test_off", None)


@pytest.mark.asyncio
async def test_browse_data_types_search(client: AsyncClient) -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type="income_vip",
            domain="financial",
            label="利润表 VIP",
            table_name="fact_income_vip",
            is_activated=True,
            browse_enabled=True,
            columns=[],
        )
    )
    try:
        response = await client.get("/api/v1/catalog/data-types?browse_only=true&q=income")
        assert response.status_code == 200
        types = [i["data_type"] for i in response.json()["items"]]
        assert "income_vip" in types

        response2 = await client.get("/api/v1/catalog/data-types?browse_only=true&q=fact_income")
        types2 = [i["data_type"] for i in response2.json()["items"]]
        assert "income_vip" in types2
    finally:
        CATALOG_REGISTRY.pop("income_vip", None)


@pytest.mark.asyncio
async def test_browse_data_includes_metadata(client: AsyncClient, db_session) -> None:
    filters = [
        CatalogFilterMeta(key="stock_code", label="股票代码", filter_type="stock_picker"),
        CatalogFilterMeta(key="trade_date", label="交易日期", filter_type="date_range"),
    ]
    register_catalog_entry(
        DataTypeEntry(
            data_type="browse_meta_test",
            domain="financial",
            label="元数据测试",
            table_name="browse_meta_test",
            is_activated=True,
            browse_enabled=True,
            filters=filters,
            columns=[
                CatalogColumnMeta(key="ts_code", label="代码", type="string"),
                CatalogColumnMeta(key="trade_date", label="日期", type="date"),
            ],
        )
    )
    await db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS browse_meta_test "
            "(id INTEGER PRIMARY KEY, ts_code VARCHAR(32), trade_date DATE)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO browse_meta_test (ts_code, trade_date) "
            "VALUES ('000001.SZ', '2024-01-02')"
        )
    )
    await db_session.commit()
    try:
        response = await client.get("/api/v1/catalog/data/browse_meta_test?limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["domain"] == "financial"
        assert body["table_name"] == "browse_meta_test"
        assert len(body["filters"]) == 2
        assert body["filters"][0]["filter_type"] == "stock_picker"
    finally:
        CATALOG_REGISTRY.pop("browse_meta_test", None)


@pytest.mark.asyncio
async def test_browse_data_date_filter(client: AsyncClient, db_session) -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type="browse_date_test",
            domain="market",
            label="日期筛选",
            table_name="browse_date_test",
            is_activated=True,
            browse_enabled=True,
            columns=[
                CatalogColumnMeta(key="ts_code", label="代码", type="string"),
                CatalogColumnMeta(key="trade_date", label="日期", type="date"),
            ],
        )
    )
    await db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS browse_date_test "
            "(id INTEGER PRIMARY KEY, ts_code VARCHAR(32), trade_date DATE)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO browse_date_test (ts_code, trade_date) VALUES "
            "('000001.SZ', '2024-01-01'), ('000001.SZ', '2024-06-01')"
        )
    )
    await db_session.commit()
    try:
        response = await client.get(
            "/api/v1/catalog/data/browse_date_test"
            "?start_date=2024-05-01&end_date=2024-12-31"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["trade_date"] == "2024-06-01"
    finally:
        CATALOG_REGISTRY.pop("browse_date_test", None)
