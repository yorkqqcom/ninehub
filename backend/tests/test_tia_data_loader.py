"""TiaDataLoader upsert aligned with schema unique_keys / constraint."""

from datetime import date

import pandas as pd
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.catalog.canonical_standard import build_canonical_schema
from app.services.tia.migration_service import TiaMigrationService
from app.services.tia.tia_data_loader import TiaDataLoader


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_upsert_maps_api_fields_to_unique_keys() -> None:
    session = _session()
    schema = build_canonical_schema("trade_cal")
    migration = TiaMigrationService()
    migration.ensure_table(session, "tia_trade_cal_loader", schema)

    df = pd.DataFrame(
        [
            {"exchange": "SSE", "cal_date": "20240102", "is_open": 1},
            {"exchange": "SSE", "cal_date": "20240103", "is_open": 1},
        ]
    )
    rows = TiaDataLoader().upsert_dataframe(session, "tia_trade_cal_loader", schema, df)
    session.commit()
    assert rows == 2

    df2 = pd.DataFrame([{"exchange": "SSE", "cal_date": "20240102", "is_open": 0}])
    rows2 = TiaDataLoader().upsert_dataframe(session, "tia_trade_cal_loader", schema, df2)
    session.commit()
    assert rows2 == 1

    inspector = inspect(session.get_bind())
    count = session.execute(
        __import__("sqlalchemy").text("SELECT COUNT(*) FROM tia_trade_cal_loader")
    ).scalar()
    assert count == 2


def test_upsert_daily_stock_code_trade_date() -> None:
    session = _session()
    schema = build_canonical_schema("daily")
    migration = TiaMigrationService()
    migration.ensure_table(session, "tia_daily_loader", schema)

    df = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20240102",
                "open": 10.0,
                "close": 10.5,
            }
        ]
    )
    rows = TiaDataLoader().upsert_dataframe(session, "tia_daily_loader", schema, df)
    session.commit()
    assert rows == 1
    inspector = inspect(session.get_bind())
    cols = {c["name"] for c in inspector.get_columns("tia_daily_loader")}
    assert "stock_code" in cols
    assert "trade_date" in cols


def test_upsert_stock_basic_ts_code_not_symbol() -> None:
    session = _session()
    live = ["ts_code", "symbol", "name", "area", "industry"]
    schema = build_canonical_schema("stock_basic", live_fields=live)
    migration = TiaMigrationService()
    migration.ensure_table(session, "tia_stock_basic_loader", schema)

    df = pd.DataFrame(
        [
            {
                "ts_code": "688820.SH",
                "symbol": "688820",
                "name": "盛合晶微",
                "area": "江苏",
                "industry": "半导体",
            }
        ]
    )
    rows = TiaDataLoader().upsert_dataframe(session, "tia_stock_basic_loader", schema, df)
    session.commit()
    assert rows == 1
    code = session.execute(
        __import__("sqlalchemy").text("SELECT stock_code FROM tia_stock_basic_loader")
    ).scalar()
    assert code == "688820.SH"


def test_stock_company_long_text_column_types() -> None:
    from app.services.tia.schema_inference import _infer_column_type

    assert _infer_column_type("introduction") == "text"
    assert _infer_column_type("main_business") == "text"
    assert _infer_column_type("business_scope") == "text"
    assert _infer_column_type("holder_name") == "text"
    assert _infer_column_type("change_reason") == "text"

    schema = build_canonical_schema("stock_company")
    types = {c["key"]: c["type"] for c in schema["columns"]}
    assert types["introduction"] == "text"
    assert types["main_business"] == "text"
    assert types["business_scope"] == "text"

    holdertrade = build_canonical_schema("stk_holdertrade")
    ht_types = {c["key"]: c["type"] for c in holdertrade["columns"]}
    assert ht_types["holder_name"] == "text"

    forecast = build_canonical_schema("forecast")
    fc_types = {c["key"]: c["type"] for c in forecast["columns"]}
    assert fc_types["change_reason"] == "text"
    assert fc_types["summary"] == "text"
