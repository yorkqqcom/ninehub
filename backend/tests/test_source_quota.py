"""Tests for Tushare source quota resolution."""

from app.services.tushare.source_quota import (
    points_to_max_calls_per_minute,
    quota_from_config,
    resolve_account_points,
    resolve_max_calls_per_minute,
)


def test_points_tier_mapping() -> None:
    assert points_to_max_calls_per_minute(120) == 50
    assert points_to_max_calls_per_minute(2000) == 200
    assert points_to_max_calls_per_minute(5000) == 500


def test_resolve_from_source_config() -> None:
    cfg = {"account_points": 2000, "max_calls_per_minute": 150}
    assert resolve_account_points(cfg) == 2000
    assert resolve_max_calls_per_minute(cfg) == 150


def test_quota_from_config_flags() -> None:
    q = quota_from_config({"account_points": 120})
    assert q["account_points"] == 120
    assert q["max_calls_per_minute"] == 50
    assert q["account_points_from_source"] is True
