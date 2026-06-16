"""TIA probe registry tests."""

from datetime import date

from app.catalog.tia_probe_registry import (
    last_trading_day,
    probeable_api_names,
    resolve_probe_params,
)


def test_probeable_includes_new_on_official() -> None:
    apis = probeable_api_names([], ["balancesheet"])
    assert apis == ["balancesheet"]


def test_plan_probe_unlimited_ignores_limit() -> None:
    from app.services.tia.scan.probe_planner import plan_probe_apis
    from app.services.tia.scan.types import OfficialApiEntry, ScanOptions

    official_map = {
        f"api_{i}": OfficialApiEntry(api=f"api_{i}", probe_category="list_limit", min_points=120)
        for i in range(10)
    }

    apis, meta = plan_probe_apis(
        local_apis=[],
        new_on_official=[],
        unchanged=[],
        official_map=official_map,
        options=ScanOptions(probe_limit=3, probe_scope="all", probe_unlimited=True),
    )
    assert len(apis) == 10
    assert meta["planned"] == 10
    assert meta["deferred"] == 0
    assert meta["probe_unlimited"] is True


def test_plan_probe_respects_limit() -> None:
    from app.services.tia.scan.probe_planner import plan_probe_apis
    from app.services.tia.scan.types import OfficialApiEntry, ScanOptions

    official_map = {
        f"api_{i}": OfficialApiEntry(api=f"api_{i}", probe_category="none", min_points=120)
        for i in range(10)
    }
    official_map["daily"] = OfficialApiEntry(
        api="daily", probe_category="ts_code_date_range", min_points=120
    )

    apis, meta = plan_probe_apis(
        local_apis=["daily"],
        new_on_official=[f"api_{i}" for i in range(5)],
        unchanged=[],
        official_map=official_map,
        options=ScanOptions(probe_limit=3, probe_scope="all"),
    )
    assert len(apis) <= 3
    assert meta["planned"] <= 3


def test_resolve_last_trading_day_placeholder() -> None:
    params = resolve_probe_params({"trade_date": "__LAST_TRADING_DAY__"})
    assert len(params["trade_date"]) == 8
    assert params["trade_date"].isdigit()


def test_last_trading_day_skips_weekend() -> None:
    day = last_trading_day(date(2024, 1, 6))
    assert day.weekday() < 5
    assert day == date(2024, 1, 5)
