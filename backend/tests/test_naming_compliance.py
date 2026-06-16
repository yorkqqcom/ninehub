"""Naming compliance audit tests."""

from app.services.catalog.naming_compliance import audit_naming_compliance, resolve_provider_id


def test_resolve_provider_from_data_type() -> None:
    assert resolve_provider_id("tushare_daily", "daily") == "tushare"
    assert resolve_provider_id("tia_daily", "daily") == "tushare"


def test_audit_naming_compliance_canonical() -> None:
    result = audit_naming_compliance(
        api_name="income",
        data_type="tushare_income",
        table_name="tushare_income",
        provider_id="tushare",
        schema={
            "api_fields": ["ts_code", "end_date"],
            "field_mappings": {"ts_code": "stock_code", "end_date": "end_date"},
            "columns": [
                {"key": "stock_code"},
                {"key": "end_date"},
            ],
        },
    )
    assert result["score"] >= 85
    assert not any("data_type" in i for i in result["issues"])
