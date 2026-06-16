"""Unique key registry — L3 DDL / upsert / preflight alignment."""

import pytest

from app.services.catalog.canonical_standard import build_canonical_schema
from app.services.tia.unique_key_registry import (
    API_UNIQUE_KEY_OVERRIDES,
    build_schema_indexes,
    enrich_schema_keys,
    probe_columns_cover_unique_keys,
    resolve_unique_keys,
    unique_constraint_name,
    validate_unique_key_columns,
)


def test_trade_cal_override_unique_keys() -> None:
    keys = resolve_unique_keys("trade_cal", ["exchange", "cal_date", "is_open"])
    assert keys == ["exchange", "cal_date"]
    assert "trade_cal" in API_UNIQUE_KEY_OVERRIDES


def test_daily_canonical_unique_keys() -> None:
    keys = resolve_unique_keys("daily", ["ts_code", "trade_date", "open"])
    assert keys == ["stock_code", "trade_date"]


def test_enrich_schema_keys_persists_indexes() -> None:
    schema = build_canonical_schema("trade_cal")
    assert schema["unique_keys"] == ["exchange", "cal_date"]
    assert schema.get("unique_constraint", {}).get("name") == (
        "uq_tushare_trade_cal_exchange_cal_date"
    )
    indexes = schema.get("indexes") or []
    assert any(i["unique"] and i["purpose"] == "upsert" for i in indexes)
    assert any(i["name"] == "ix_tushare_trade_cal_exchange" for i in indexes)


def test_validate_unique_key_not_null() -> None:
    schema = {
        "columns": [
            {"key": "exchange", "type": "string", "nullable": True},
            {"key": "cal_date", "type": "date", "nullable": True},
        ],
        "unique_keys": ["exchange", "cal_date"],
        "field_mappings": {"exchange": "exchange", "cal_date": "cal_date"},
        "api_fields": ["exchange", "cal_date"],
    }
    errors = validate_unique_key_columns(schema)
    assert any("NOT NULL" in e for e in errors)

    schema = enrich_schema_keys(schema, "trade_cal", table_name="tia_trade_cal")
    assert validate_unique_key_columns(schema) == []


def test_probe_columns_cover_unique_keys() -> None:
    schema = enrich_schema_keys(build_canonical_schema("trade_cal"), "trade_cal")
    ok, missing = probe_columns_cover_unique_keys(schema, ["exchange", "cal_date", "is_open"])
    assert ok is True
    assert missing == []

    ok2, missing2 = probe_columns_cover_unique_keys(schema, ["cal_date"])
    assert ok2 is False
    assert "exchange" in missing2


def test_unique_constraint_name_stable() -> None:
    assert unique_constraint_name("tia_daily", ["stock_code", "trade_date"]) == (
        "uq_tia_daily_stock_code_trade_date"
    )


def test_top_list_trade_date_only() -> None:
    keys = resolve_unique_keys("top_list", ["trade_date", "ts_code", "name"])
    assert keys == ["trade_date"]


def test_daily_basic_unique_keys() -> None:
    keys = resolve_unique_keys("daily_basic", ["ts_code", "trade_date", "turnover_rate"])
    assert keys == ["stock_code", "trade_date"]
    assert "daily_basic" in API_UNIQUE_KEY_OVERRIDES


def test_share_float_unique_keys() -> None:
    keys = resolve_unique_keys("share_float", ["ts_code", "ann_date", "float_share"])
    assert keys == ["stock_code", "ann_date"]


def test_index_daily_unique_keys() -> None:
    keys = resolve_unique_keys("index_daily", ["ts_code", "trade_date", "close"])
    assert keys == ["stock_code", "trade_date"]

    schema = enrich_schema_keys(build_canonical_schema("daily"), "daily")
    names = {i["name"] for i in build_schema_indexes(schema, "tushare_daily")}
    assert "uq_tushare_daily_stock_code_trade_date" in names
    assert "ix_tushare_daily_stock_code" in names
    assert "ix_tushare_daily_trade_date" in names
