"""Data Browser query engine tests."""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import Column, Date, Float, MetaData, String, Table, insert

from app.catalog.registry import CATALOG_REGISTRY, DataTypeEntry, register_catalog_entry
from app.schemas.catalog import CatalogColumnMeta, CatalogFilterMeta
from app.schemas.query_browser import UniverseCustom
from app.services.query.browser_query import BrowserQueryService
from app.services.query.indicator_registry import IndicatorRegistry
from app.services.query.universe_resolver import UniverseResolver
from app.services.trading_calendar.service import TradingCalendarService


def _register_browser_catalog() -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_stock_basic",
            domain="basic",
            label="股票列表",
            table_name="tushare_stock_basic",
            is_activated=True,
            browse_enabled=True,
            columns=[
                CatalogColumnMeta(key="stock_code", label="代码", type="string"),
                CatalogColumnMeta(key="name", label="名称", type="string"),
                CatalogColumnMeta(key="exchange", label="交易所", type="string"),
                CatalogColumnMeta(key="industry", label="行业", type="string"),
                CatalogColumnMeta(key="delist_date", label="退市日期", type="date"),
            ],
            filters=[],
        )
    )
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_daily",
            domain="market",
            label="日线",
            table_name="tushare_daily",
            is_activated=True,
            browse_enabled=True,
            columns=[
                CatalogColumnMeta(key="stock_code", label="代码", type="string"),
                CatalogColumnMeta(key="trade_date", label="日期", type="date"),
                CatalogColumnMeta(key="open", label="开盘", type="number"),
                CatalogColumnMeta(key="close", label="收盘", type="number"),
                CatalogColumnMeta(key="high", label="最高", type="number"),
                CatalogColumnMeta(key="low", label="最低", type="number"),
            ],
            filters=[],
        )
    )
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_adj_factor",
            domain="market",
            label="复权因子",
            table_name="tushare_adj_factor",
            is_activated=True,
            columns=[
                CatalogColumnMeta(key="stock_code", label="代码", type="string"),
                CatalogColumnMeta(key="trade_date", label="日期", type="date"),
                CatalogColumnMeta(key="adj_factor", label="因子", type="number"),
            ],
            filters=[],
        )
    )


async def _seed_tables(db_session) -> None:
    metadata = MetaData()
    basic = Table(
        "tushare_stock_basic",
        metadata,
        Column("stock_code", String, primary_key=True),
        Column("name", String),
        Column("exchange", String),
        Column("industry", String),
        Column("delist_date", Date),
    )
    daily = Table(
        "tushare_daily",
        metadata,
        Column("stock_code", String),
        Column("trade_date", Date),
        Column("open", Float),
        Column("close", Float),
        Column("high", Float),
        Column("low", Float),
    )
    adj = Table(
        "tushare_adj_factor",
        metadata,
        Column("stock_code", String),
        Column("trade_date", Date),
        Column("adj_factor", Float),
    )
    conn = await db_session.connection()
    await conn.run_sync(metadata.create_all)
    await db_session.execute(
        insert(basic),
        [
            {"stock_code": "000001.SZ", "name": "平安银行", "exchange": "SZSE", "industry": "银行"},
            {"stock_code": "600900.SH", "name": "长江电力", "exchange": "SSE", "industry": "水电"},
        ],
    )
    await db_session.execute(
        insert(daily),
        [
            {
                "stock_code": "000001.SZ",
                "trade_date": date(2024, 11, 20),
                "open": 10.0,
                "close": 10.5,
                "high": 10.8,
                "low": 9.8,
            },
            {
                "stock_code": "600900.SH",
                "trade_date": date(2024, 11, 20),
                "open": 20.0,
                "close": 21.0,
                "high": 21.5,
                "low": 19.5,
            },
        ],
    )
    await db_session.execute(
        insert(adj),
        [
            {"stock_code": "000001.SZ", "trade_date": date(2024, 11, 20), "adj_factor": 1.2},
            {"stock_code": "600900.SH", "trade_date": date(2024, 11, 20), "adj_factor": 2.0},
        ],
    )
    await db_session.commit()


@pytest.fixture
def browser_catalog():
    _register_browser_catalog()
    yield
    for k in ("tushare_stock_basic", "tushare_daily", "tushare_adj_factor"):
        CATALOG_REGISTRY.pop(k, None)


@pytest.mark.asyncio
async def test_trading_calendar_nearest(db_session, browser_catalog):
    cal = TradingCalendarService()
    d, adjusted = cal.nearest_trading_day_on_or_before(date(2024, 11, 23))  # Saturday
    assert adjusted is True
    assert d.weekday() < 5


@pytest.mark.asyncio
async def test_universe_custom_empty(db_session, browser_catalog):
    resolver = UniverseResolver()
    codes = await resolver.resolve(db_session, UniverseCustom(codes=[]))
    assert codes == []


@pytest.mark.asyncio
async def test_browser_execute_wide_table(db_session, browser_catalog):
    await _seed_tables(db_session)
    svc = BrowserQueryService()
    from app.schemas.query_browser import BrowserExecuteRequest, IndicatorSelection, UniverseCustom

    req = BrowserExecuteRequest(
        universe=UniverseCustom(codes=["000001.SZ", "600900.SH"]),
        as_of_date=date(2024, 11, 20),
        indicators=[
            IndicatorSelection(id="tushare_stock_basic.exchange"),
            IndicatorSelection(id="tushare_daily.close", adjust="none"),
        ],
        limit=50,
    )
    result = await svc.execute(db_session, req, user_id=1)
    assert result.total == 2
    assert len(result.items) == 2
    assert result.items[0]["stock_code"] in ("000001.SZ", "600900.SH")
    assert result.aggregations


@pytest.mark.asyncio
async def test_browser_meta_api(client: AsyncClient, browser_catalog):
    r = await client.get("/api/v1/query/browser/meta")
    assert r.status_code == 200
    body = r.json()
    assert "indicator_tree" in body
    assert "indicators_flat" in body
    assert len(body["indicators_flat"]) >= 1
    assert len(body["indicator_tree"]) >= 1
    assert "dimensions" in body
    assert any(t["id"] == "wind_ohlc_demo" for t in body["system_templates"])


@pytest.mark.asyncio
async def test_browser_execute_daily_date_fallback(db_session, browser_catalog):
    await _seed_tables(db_session)
    svc = BrowserQueryService()
    from app.schemas.query_browser import BrowserExecuteRequest, IndicatorSelection, UniverseCustom

    req = BrowserExecuteRequest(
        universe=UniverseCustom(codes=["000001.SZ"]),
        as_of_date=date(2024, 11, 21),
        indicators=[IndicatorSelection(id="tushare_daily.open")],
        limit=50,
    )
    result = await svc.execute(db_session, req, user_id=1)
    assert result.meta.effective_date == "2024-11-20"
    assert result.items[0]["tushare_daily.open"] == 10.0
    assert any("回退" in w.reason for w in result.warnings)


@pytest.mark.asyncio
async def test_browser_execute_api(client: AsyncClient, db_session, browser_catalog):
    await _seed_tables(db_session)
    payload = {
        "universe": {"type": "custom", "codes": ["000001.SZ"]},
        "as_of_date": "2024-11-20",
        "indicators": [
            {"id": "tushare_stock_basic.exchange"},
            {"id": "tushare_daily.open"},
        ],
        "limit": 10,
    }
    r = await client.post("/api/v1/query/browser/execute", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["tushare_daily.open"] == 10.0


@pytest.mark.asyncio
async def test_browser_universe_empty_422(client: AsyncClient, browser_catalog):
    payload = {
        "universe": {"type": "custom", "codes": []},
        "as_of_date": "2024-11-20",
        "indicators": [{"id": "tushare_stock_basic.exchange"}],
    }
    r = await client.post("/api/v1/query/browser/execute", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_indicator_registry_tree(browser_catalog):
    reg = IndicatorRegistry()
    tree = reg.build_tree()
    assert isinstance(tree, list)
    flat = reg.list_indicators()
    assert any(i.id == "tushare_daily.close" for i in flat)


def test_enrich_with_coverage_static_column(browser_catalog):
    reg = IndicatorRegistry()
    refs = reg.enrich_with_coverage(
        {"tushare_stock_basic": 100, "tushare_daily": 1000},
        {
            ("tushare_stock_basic", "exchange"): 0,
            ("tushare_stock_basic", "industry"): 50,
        },
    )
    ex = next(r for r in refs if r.id == "tushare_stock_basic.exchange")
    ind = next(r for r in refs if r.id == "tushare_stock_basic.industry")
    assert ex.data_ready is False
    assert ind.data_ready is True
    daily = next(r for r in refs if r.id == "tushare_daily.open")
    assert daily.data_ready is True


@pytest.mark.asyncio
async def test_browser_warns_empty_static_column(db_session, browser_catalog):
    await _seed_tables(db_session)
    svc = BrowserQueryService()
    from app.schemas.query_browser import BrowserExecuteRequest, IndicatorSelection, UniverseCustom

    req = BrowserExecuteRequest(
        universe=UniverseCustom(codes=["000001.SZ"]),
        as_of_date=date(2024, 11, 20),
        indicators=[
            IndicatorSelection(id="tushare_stock_basic.delist_date"),
            IndicatorSelection(id="tushare_daily.open"),
        ],
        limit=50,
    )
    result = await svc.execute(db_session, req, user_id=1)
    assert any(w.indicator_id == "tushare_stock_basic.delist_date" for w in result.warnings)


@pytest.mark.asyncio
async def test_browser_export_sync(client: AsyncClient, db_session, browser_catalog):
    await _seed_tables(db_session)
    payload = {
        "query": {
            "universe": {"type": "custom", "codes": ["000001.SZ"]},
            "as_of_date": "2024-11-20",
            "indicators": [{"id": "tushare_daily.close"}],
            "limit": 100,
        },
        "format": "csv",
        "async_job": False,
    }
    r = await client.post("/api/v1/query/browser/export", json=payload)
    assert r.status_code == 200
    assert "000001.SZ" in r.json()["content"]


@pytest.mark.asyncio
async def test_browser_export_sync_xlsx(client: AsyncClient, db_session, browser_catalog):
    await _seed_tables(db_session)
    payload = {
        "query": {
            "universe": {"type": "custom", "codes": ["000001.SZ"]},
            "as_of_date": "2024-11-20",
            "indicators": [{"id": "tushare_daily.close"}],
            "limit": 100,
        },
        "format": "xlsx",
        "async_job": False,
    }
    r = await client.post("/api/v1/query/browser/export", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["download_url"]
    assert "/exports/sync/" in body["download_url"]
    dl = await client.get(body["download_url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@pytest.mark.asyncio
async def test_browser_readiness(client: AsyncClient, browser_catalog):
    r = await client.get("/api/v1/query/browser/readiness")
    assert r.status_code == 200
    body = r.json()
    assert "p0_ok" in body
    assert isinstance(body["items"], list)
    assert any(i["level"] == "p0" for i in body["items"])


@pytest.mark.asyncio
async def test_browser_share_roundtrip(client: AsyncClient, browser_catalog):
    create = await client.post(
        "/api/v1/query/browser/share",
        json={"payload": {"indicators": [{"id": "tushare_daily.close"}]}},
    )
    assert create.status_code == 200
    token = create.json()["share_token"]
    get = await client.get(f"/api/v1/query/browser/share/{token}")
    assert get.status_code == 200
    assert get.json()["indicators"][0]["id"] == "tushare_daily.close"


@pytest.mark.asyncio
async def test_browser_soft_indicator_warning(db_session, browser_catalog):
    await _seed_tables(db_session)
    from app.schemas.query_browser import BrowserExecuteRequest, IndicatorSelection, UniverseCustom

    indicators = [
        IndicatorSelection(id=f"tushare_stock_basic.{c}")
        for c in ("stock_code", "name", "exchange")
    ] + [
        IndicatorSelection(id="tushare_daily.open"),
        IndicatorSelection(id="tushare_daily.close"),
    ]
    # pad to 21 indicators using duplicate column refs won't work - use many stock_basic cols
    # instead test with 21 unique refs from registry
    reg_ids = [f"tushare_stock_basic.{c}" for c in ("stock_code", "name", "exchange")]
    reg_ids += [f"tushare_daily.{c}" for c in ("open", "close", "high", "low")]
    while len(reg_ids) < 21:
        reg_ids.append("tushare_daily.close")
    req = BrowserExecuteRequest(
        universe=UniverseCustom(codes=["000001.SZ"]),
        as_of_date=date(2024, 11, 20),
        indicators=[IndicatorSelection(id=i) for i in reg_ids[:21]],
        limit=10,
    )
    result = await BrowserQueryService().execute(db_session, req)
    assert any("超过建议值" in (w.reason or "") for w in result.warnings)


async def _seed_sw_classify(db_session) -> None:
    metadata = MetaData()
    classify = Table(
        "tushare_index_classify",
        metadata,
        Column("index_code", String),
        Column("industry_name", String),
        Column("level", String),
        Column("src", String),
    )
    member = Table(
        "tushare_index_member_all",
        metadata,
        Column("l1_code", String),
        Column("stock_code", String),
        Column("is_new", String),
    )
    conn = await db_session.connection()
    await conn.run_sync(metadata.create_all)
    rows = [
        {"index_code": "801010.SI", "industry_name": "农林牧渔", "level": "L1", "src": "SW2021"},
        {"index_code": "801030.SI", "industry_name": "基础化工", "level": "L1", "src": "SW2021"},
    ]
    await db_session.execute(insert(classify), rows)
    await db_session.execute(
        insert(member),
        [
            {"l1_code": "801010.SI", "stock_code": "000001.SZ", "is_new": "Y"},
            {"l1_code": "801030.SI", "stock_code": "600900.SH", "is_new": "Y"},
        ],
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_sw_l1_dimensions_from_classify(db_session, browser_catalog):
    from app.services.query import dimension_registry as dr

    dr._sw_l1_cache.clear()
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_index_classify",
            domain="index",
            label="申万行业分类",
            table_name="tushare_index_classify",
            is_activated=True,
            columns=[],
            filters=[],
        )
    )
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_index_member_all",
            domain="index",
            label="申万行业成分",
            table_name="tushare_index_member_all",
            is_activated=True,
            columns=[],
            filters=[],
        )
    )
    await _seed_sw_classify(db_session)

    from app.services.query.dimension_registry import DimensionRegistry

    dims = await DimensionRegistry().list_dimensions(db_session)
    sw = [d for d in dims if d.category == "sw"]
    assert len(sw) == 2
    assert sw[0].id.startswith("sw:L1:")
    assert sw[0].label.startswith("申万一级·")
    assert sw[0].available is True


@pytest.mark.asyncio
async def test_sw_universe_preset(db_session, browser_catalog):
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_index_classify",
            domain="index",
            label="申万行业分类",
            table_name="tushare_index_classify",
            is_activated=True,
            columns=[],
            filters=[],
        )
    )
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_index_member_all",
            domain="index",
            label="申万行业成分",
            table_name="tushare_index_member_all",
            is_activated=True,
            columns=[],
            filters=[],
        )
    )
    await _seed_sw_classify(db_session)

    from app.schemas.query_browser import UniversePreset

    codes = await UniverseResolver().resolve(db_session, UniversePreset(preset="sw:L1:801010.SI"))
    assert codes == ["000001.SZ"]


@pytest.mark.asyncio
async def test_browser_cache_hit(client, db_session, browser_catalog):
    await _seed_tables(db_session)
    payload = {
        "universe": {"type": "custom", "codes": ["000001.SZ"]},
        "as_of_date": "2024-11-20",
        "indicators": [{"id": "tushare_daily.close"}],
        "limit": 50,
        "force_refresh": True,
    }
    r1 = await client.post("/api/v1/query/browser/execute", json=payload)
    assert r1.status_code == 200
    assert r1.json().get("cache_hit") is False
    payload["force_refresh"] = False
    r2 = await client.post("/api/v1/query/browser/execute", json=payload)
    assert r2.status_code == 200
    assert r2.json().get("cache_hit") is True


@pytest.mark.asyncio
async def test_browser_template_crud(client):
    create = await client.post(
        "/api/v1/query/browser/templates",
        json={"name": "test tpl", "payload": {"indicators": []}},
    )
    assert create.status_code == 200
    tid = create.json()["id"]
    upd = await client.put(
        f"/api/v1/query/browser/templates/{tid}",
        json={"name": "renamed"},
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "renamed"
    delete = await client.delete(f"/api/v1/query/browser/templates/{tid}")
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_browser_watchlist_crud(client, db_session, browser_catalog):
    await _seed_tables(db_session)
    create = await client.post(
        "/api/v1/query/browser/watchlists",
        json={
            "name": "my pool",
            "universe": {"type": "custom", "codes": ["000001.SZ", "600900.SH"]},
        },
    )
    assert create.status_code == 200
    wid = create.json()["id"]
    assert len(create.json()["codes"]) == 2
    get = await client.get(f"/api/v1/query/browser/watchlists/{wid}")
    assert get.status_code == 200
    delete = await client.delete(f"/api/v1/query/browser/watchlists/{wid}")
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_browser_audit_list(client, db_session, browser_catalog):
    await _seed_tables(db_session)
    payload = {
        "universe": {"type": "custom", "codes": ["000001.SZ"]},
        "as_of_date": "2024-11-20",
        "indicators": [{"id": "tushare_daily.close"}],
        "force_refresh": True,
    }
    await client.post("/api/v1/query/browser/execute", json=payload)
    audit = await client.get("/api/v1/query/browser/audit?limit=5")
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1


@pytest.mark.asyncio
async def test_browser_multi_date_execute(client, db_session, browser_catalog):
    await _seed_tables(db_session)
    payload = {
        "universe": {"type": "custom", "codes": ["000001.SZ"]},
        "as_of_date": "2024-11-20",
        "dates": ["2024-11-20", "2024-11-21"],
        "indicators": [{"id": "tushare_daily.close"}],
        "limit": 50,
    }
    r = await client.post("/api/v1/query/browser/execute", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["multi_date_mode"] is True
    col_ids = [c["id"] for c in body["columns"]]
    assert any("@" in cid for cid in col_ids)
