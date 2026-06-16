"""trade_cal unique keys and zero-row upsert detection."""

from app.services.catalog.canonical_standard import build_canonical_schema, normalize_unique_keys


def test_trade_cal_unique_keys_exchange_cal_date() -> None:
    keys = normalize_unique_keys(["exchange", "cal_date"])
    assert keys == ["exchange", "cal_date"]


def test_trade_cal_schema_unique_keys() -> None:
    schema = build_canonical_schema("trade_cal")
    assert schema["unique_keys"] == ["exchange", "cal_date"]
    assert "cal_date" in [c["key"] for c in schema["columns"]]
