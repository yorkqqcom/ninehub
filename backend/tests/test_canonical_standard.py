"""Canonical data standard tests — DDL alignment."""

import pandas as pd

from app.services.catalog.canonical_standard import (
    apply_dataframe_field_mappings,
    build_canonical_schema,
    validate_canonical_for_ddl,
)
from app.services.tia.schema_inference import infer_schema_for_api


def test_canonical_schema_maps_ts_code_to_stock_code() -> None:
    schema = build_canonical_schema("income")
    keys = [c["key"] for c in schema["columns"]]
    assert "stock_code" in keys
    assert "ts_code" not in keys
    assert schema["field_mappings"]["ts_code"] == "stock_code"
    assert schema["unique_keys"] == ["stock_code", "end_date"]
    assert schema["data_standard"]["approved"] is True
    assert validate_canonical_for_ddl(schema, "income") == []


def test_infer_schema_delegates_to_canonical() -> None:
    schema = infer_schema_for_api("daily")
    assert "field_mappings" in schema
    assert schema["field_mappings"]["ts_code"] == "stock_code"
    assert validate_canonical_for_ddl(schema, "daily") == []


def test_validate_rejects_unapproved_schema() -> None:
    schema = {"columns": [{"key": "x", "type": "string"}], "unique_keys": ["x"]}
    errors = validate_canonical_for_ddl(schema, "daily")
    assert any("not approved" in e for e in errors)


def test_apply_field_mappings_ts_code_wins_over_symbol() -> None:
    live = ["ts_code", "symbol", "name"]
    schema = build_canonical_schema("stock_basic", live_fields=live)
    df = pd.DataFrame([{"ts_code": "688820.SH", "symbol": "688820", "name": "盛合晶微"}])
    mapped = apply_dataframe_field_mappings(df, schema)
    assert list(mapped.columns).count("stock_code") == 1
    assert mapped.iloc[0]["stock_code"] == "688820.SH"
    assert "symbol" in mapped.columns
