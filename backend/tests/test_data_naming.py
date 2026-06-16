"""Tests for field override registry and naming constants."""

from app.catalog.field_override_registry import resolve_field_override
from app.services.catalog.canonical_standard import build_canonical_schema
from app.services.tia.constants import (
    api_to_data_type,
    api_to_table_name,
    data_type_aliases,
    legacy_data_type,
    resolve_canonical_data_type,
)


def test_api_to_data_type_includes_provider() -> None:
    assert api_to_data_type("daily") == "tushare_daily"
    assert api_to_data_type("daily", provider="akshare") == "akshare_daily"


def test_legacy_data_type_alias() -> None:
    assert legacy_data_type("daily") == "tia_daily"
    assert "tia_daily" in data_type_aliases("daily")
    assert data_type_aliases("daily")[0] == "tushare_daily"


def test_resolve_canonical_data_type_from_legacy() -> None:
    assert resolve_canonical_data_type("tia_income") == "tushare_income"
    assert resolve_canonical_data_type("tushare_income") == "tushare_income"


def test_api_to_table_name_matches_data_type() -> None:
    assert api_to_table_name("daily") == "tushare_daily"


def test_change_maps_to_change_amount_for_daily() -> None:
    assert resolve_field_override("change", api_name="daily") == "change_amount"
    schema = build_canonical_schema(
        "daily",
        actual_fields=["ts_code", "trade_date", "open", "change"],
    )
    assert schema["field_mappings"].get("change") == "change_amount"
    keys = [c["key"] for c in schema["columns"]]
    assert "change_amount" in keys
    assert "change" not in keys


def test_forecast_type_maps_to_fcst_type() -> None:
    assert resolve_field_override("type", api_name="forecast") == "fcst_type"


def test_symbol_maps_to_stock_code() -> None:
    assert resolve_field_override("symbol", provider="akshare") == "stock_code"
