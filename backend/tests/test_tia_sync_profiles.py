"""Sync profile resolution for post-L3 task scheduling."""

from app.services.tia.sync_profiles import resolve_sync_profile


def test_stock_basic_snapshot_profile() -> None:
    profile = resolve_sync_profile("stock_basic")
    assert profile.mode == "snapshot"
    assert profile.schedule_cron == "0 8 * * 1-5"
    assert profile.trigger_initial is True


def test_daily_date_range_profile() -> None:
    profile = resolve_sync_profile("daily")
    assert profile.mode == "date_range"
    assert profile.schedule_cron == "0 18 * * 1-5"
    assert profile.max_codes_per_run == 50


def test_trade_cal_exchange_date_range_profile() -> None:
    profile = resolve_sync_profile("trade_cal")
    assert profile.mode == "exchange_date_range"
    assert profile.max_api_calls_per_run == 200
