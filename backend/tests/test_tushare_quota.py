"""Tushare quota / collect points validation tests."""

from app.catalog.registry import entry_from_override, register_catalog_entry
from app.services.tushare.quota import api_min_points, data_type_min_points


def test_trade_cal_api_min_points_2000() -> None:
    assert api_min_points("trade_cal") == 2000


def test_data_type_min_points_uses_max_of_registry_and_canonical() -> None:
    register_catalog_entry(
        entry_from_override(
            api_name="trade_cal",
            data_type="tushare_trade_cal",
            domain="basic",
            label="交易日历",
            min_points=120,
            table_name="tushare_trade_cal",
            is_activated=True,
        )
    )
    try:
        assert data_type_min_points("tushare_trade_cal") == 2000
    finally:
        from app.catalog.registry import CATALOG_REGISTRY

        CATALOG_REGISTRY.pop("tushare_trade_cal", None)
