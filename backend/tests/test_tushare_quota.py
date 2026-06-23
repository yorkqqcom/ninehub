"""Tushare quota / collect points validation tests."""

import time

from app.catalog.registry import entry_from_override, register_catalog_entry
from app.services.collectors import tushare as tushare_collector
from app.services.tushare.quota import api_min_points, data_type_min_points
from app.services.tushare.source_quota import API_INTERFACE_LIMITS, api_max_calls_per_minute


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


def test_stk_holdertrade_interface_limit() -> None:
    assert API_INTERFACE_LIMITS["stk_holdertrade"] == 100
    assert api_max_calls_per_minute("stk_holdertrade") == 100
    assert api_max_calls_per_minute("daily") is None


def test_wait_before_pro_call_enforces_per_api_cap(monkeypatch) -> None:
    tushare_collector._call_times.clear()
    tushare_collector._api_call_times.clear()
    sleeps: list[float] = []
    clock = {"t": 1000.0}

    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    for _ in range(100):
        clock["t"] += 0.01
        tushare_collector.wait_before_pro_call(200, api_name="stk_holdertrade")

    clock["t"] += 0.5
    tushare_collector.wait_before_pro_call(200, api_name="stk_holdertrade")

    assert sleeps
    assert sleeps[-1] > 50.0
