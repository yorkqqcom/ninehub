"""Collect pattern inference tests — trade_cal class API mislabel prevention."""

import pytest

from app.services.tia.collect_pattern import (
    API_PATTERN_OVERRIDES,
    COLLECT_PATTERN_REGISTRY,
    PATTERN_EXAMPLE_APIS,
    discover_mislabeled_apis,
    enrich_schema_collect,
    infer_collect_pattern,
    resolve_collect_pattern,
    validate_collect_pattern,
)
from app.services.tia.sync_profiles import resolve_sync_profile


def test_infer_exchange_date_range_from_params() -> None:
    params = {"exchange": "SSE", "start_date": "20240101", "end_date": "20240105"}
    assert infer_collect_pattern(params, expected_fields=["exchange", "cal_date"]) == (
        "exchange_date_range"
    )


def test_infer_trade_date_from_params() -> None:
    params = {"trade_date": "20240102"}
    assert infer_collect_pattern(params) == "trade_date"


def test_infer_ts_code_date_range() -> None:
    params = {"ts_code": "000001.SZ", "start_date": "20240102", "end_date": "20240105"}
    assert infer_collect_pattern(params) == "ts_code_date_range"


def test_trade_cal_resolves_exchange_date_range() -> None:
    result = resolve_collect_pattern("trade_cal")
    assert result.pattern_key == "exchange_date_range"
    assert result.mode == "exchange_date_range"
    assert result.probe_spec_source == "template:trade_cal"
    assert result.catalog_probe_category == "trade_date"
    assert result.pattern_mismatch is True


def test_trade_cal_sync_profile() -> None:
    profile = resolve_sync_profile("trade_cal")
    assert profile.mode == "exchange_date_range"


def test_trade_cal_validation_not_blocked_with_override() -> None:
    validation = validate_collect_pattern("trade_cal")
    assert "trade_cal" in API_PATTERN_OVERRIDES
    assert validation.blocking_errors == []


def test_enrich_schema_collect_persists_mode() -> None:
    schema: dict = {"columns": [{"key": "cal_date", "type": "date"}]}
    enriched = enrich_schema_collect(schema, "trade_cal")
    assert enriched["collect"]["mode"] == "exchange_date_range"
    assert enriched["collect"]["pattern"] == "exchange_date_range"
    assert enriched["collect_pattern"]["pattern_mismatch"] is True
    profile = resolve_sync_profile("trade_cal", enriched)
    assert profile.mode == "exchange_date_range"


def test_daily_resolves_date_range() -> None:
    result = resolve_collect_pattern("daily")
    assert result.pattern_key == "ts_code_date_range"
    assert result.mode == "date_range"


def test_top_list_resolves_trade_date() -> None:
    result = resolve_collect_pattern("top_list")
    assert result.mode == "trade_date"
    assert result.pattern_key in ("trade_date", "generic")


def test_discover_mislabeled_includes_trade_cal() -> None:
    findings = discover_mislabeled_apis()
    trade_cal = next((f for f in findings if f["api_name"] == "trade_cal"), None)
    assert trade_cal is not None
    assert trade_cal["inferred_pattern"] == "exchange_date_range"
    assert trade_cal["has_override"] is True


def test_pattern_registry_covers_all_modes() -> None:
    modes = {v["mode"] for v in COLLECT_PATTERN_REGISTRY.values()}
    assert "exchange_date_range" in modes
    assert "trade_date" in modes
    assert "date_range" in modes


def test_pattern_examples_reference_trade_cal() -> None:
    assert "trade_cal" in PATTERN_EXAMPLE_APIS["exchange_date_range"]


def test_stock_basic_probe_params_all_exchanges() -> None:
    from app.services.tia.collect_pattern import resolve_probe_params_for_api

    params = resolve_probe_params_for_api("stock_basic", {})
    assert params == {"exchange": "", "list_status": "L"}


def test_blocking_when_catalog_conflicts_with_inferred_mode() -> None:
    """Simulate mislabeled calendar API without business override."""
    from app.services.tia.collect_pattern import CollectPatternResult, validate_collect_pattern

    fake = CollectPatternResult(
        pattern_key="exchange_date_range",
        mode="exchange_date_range",
        label="test",
        api_calls_hint="1",
        catalog_probe_category="trade_date",
        pattern_mismatch=True,
        estimated_calls_per_year=1,
    )

    class FakeValidation:
        result = fake
        blocking_errors: list[str] = []

    from app.services import tia as _tia_pkg  # noqa: F401
    from app.services.tia import collect_pattern as cp

    original = cp.resolve_collect_pattern
    original_overrides = dict(cp.API_PATTERN_OVERRIDES)

    def fake_resolve(api_name: str, official_entry=None):
        if api_name == "fake_new_cal":
            return fake
        return original(api_name, official_entry)

    cp.resolve_collect_pattern = fake_resolve
    cp.API_PATTERN_OVERRIDES.pop("fake_new_cal", None)
    try:
        validation = validate_collect_pattern("fake_new_cal")
        assert validation.blocking_errors
        assert "exchange_date_range" in validation.blocking_errors[0]
    finally:
        cp.resolve_collect_pattern = original
        cp.API_PATTERN_OVERRIDES.clear()
        cp.API_PATTERN_OVERRIDES.update(original_overrides)
