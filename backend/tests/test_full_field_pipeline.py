"""Full-field schema pipeline — merge registry, live probe, DDL, and collect."""

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.catalog.canonical_standard import build_canonical_schema, resolve_schema_for_ddl
from app.services.catalog.field_resolution import (
    live_fields_from_activation_steps,
    merge_field_lists,
    resolve_api_fields,
)
from app.services.tia.migration_service import TiaMigrationService
from app.services.tia.tia_data_loader import TiaDataLoader
from app.sync.tia_collect.params import sanitize_collect_params


def test_merge_field_lists_preserves_order() -> None:
    merged = merge_field_lists(["ts_code", "trade_date"], ["trade_date", "amount"])
    assert merged == ["ts_code", "trade_date", "amount"]


def test_daily_schema_includes_registry_output_fields() -> None:
    fields = resolve_api_fields("daily")
    assert "pre_close" in fields
    assert "amount" in fields
    assert "change" in fields
    schema = build_canonical_schema("daily")
    keys = [c["key"] for c in schema["columns"]]
    assert len(keys) == 13
    assert "change_amount" in keys
    assert "stock_code" in keys
    assert "ah_vol" in keys
    assert "ah_amount" in keys


def test_daily_schema_merges_live_probe_extra_fields() -> None:
    live = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "turnover_rate"]
    schema = build_canonical_schema("daily", live_fields=live)
    keys = {c["key"] for c in schema["columns"]}
    assert keys == {
        "stock_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "turnover_rate",
    }
    assert schema["built_from"] == "live_actual"


def test_live_fields_only_excludes_doc_registry_when_present() -> None:
    live = ["ts_code", "trade_date", "open", "high", "low", "close", "vol"]
    fields = resolve_api_fields("daily", live_fields=live)
    assert fields == live
    assert "pre_close" not in fields
    assert "amount" not in fields


def test_income_schema_from_live_actual_not_template() -> None:
    live = [
        "ts_code",
        "ann_date",
        "end_date",
        "basic_eps",
        "total_revenue",
        "n_income",
    ]
    schema = build_canonical_schema("income", live_fields=live)
    keys = {c["key"] for c in schema["columns"]}
    assert len(keys) == len(live)
    assert "stock_code" in keys
    assert schema["built_from"] == "live_actual"


def test_resolve_api_fields_require_live_raises() -> None:
    import pytest

    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError, match="live probe"):
        resolve_api_fields("income", require_live_actual=True)


def test_resolve_schema_for_ddl_uses_live_fields_from_activation_steps() -> None:
    steps = {
        "preflight_test": {
            "status": "success",
            "actual_fields": ["exchange", "cal_date", "is_open", "pretrade_date"],
        }
    }
    live = live_fields_from_activation_steps(steps)
    assert live == ["exchange", "cal_date", "is_open", "pretrade_date"]
    schema = resolve_schema_for_ddl("trade_cal", None, force_rebuild=True, live_fields=live)
    keys = {c["key"] for c in schema["columns"]}
    assert keys >= {"exchange", "cal_date", "is_open", "pretrade_date"}


def test_sanitize_collect_params_drops_fields_filter() -> None:
    params = sanitize_collect_params(
        {"ts_code": "000001.SZ", "period": "20231231", "fields": "ts_code,end_date,total_assets"}
    )
    assert "fields" not in params
    assert params["ts_code"] == "000001.SZ"


def test_upsert_daily_persists_all_schema_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    schema = build_canonical_schema("daily")
    migration = TiaMigrationService()
    migration.ensure_table(session, "tushare_daily_full", schema)

    df = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20240102",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "pre_close": 10.2,
                "change": 0.3,
                "pct_chg": 2.94,
                "vol": 1000,
                "amount": 10500.0,
                "ah_vol": 500,
                "ah_amount": 5200.0,
            }
        ]
    )
    rows = TiaDataLoader().upsert_dataframe(session, "tushare_daily_full", schema, df)
    session.commit()
    assert rows == 1

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("tushare_daily_full")}
    assert {"stock_code", "pre_close", "change_amount", "pct_chg", "amount", "ah_vol", "ah_amount"} <= cols

    row = session.execute(text("SELECT * FROM tushare_daily_full")).mappings().first()
    assert row["amount"] is not None
    assert row["change_amount"] is not None
    assert row["ah_vol"] == 500
    assert row["ah_amount"] == 5200.0
