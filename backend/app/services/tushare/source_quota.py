"""Resolve Tushare account points and API rate limits from source config or env."""

from __future__ import annotations

from typing import Any, Optional

from app.core.config import get_settings


def points_to_max_calls_per_minute(account_points: int) -> int:
    """Map Tushare account tier to per-minute API call cap (doc_id=290)."""
    if account_points >= 5000:
        return 500
    if account_points >= 2000:
        return 200
    return 50


def resolve_account_points(source_config: Optional[dict[str, Any]] = None) -> int:
    if source_config is not None and source_config.get("account_points") is not None:
        return int(source_config["account_points"])
    return get_settings().tushare_account_points


def resolve_max_calls_per_minute(source_config: Optional[dict[str, Any]] = None) -> int:
    settings = get_settings()
    if source_config is not None and source_config.get("max_calls_per_minute") is not None:
        return int(source_config["max_calls_per_minute"])
    if settings.tushare_max_calls_per_minute is not None:
        return settings.tushare_max_calls_per_minute
    return points_to_max_calls_per_minute(resolve_account_points(source_config))


def quota_from_config(source_config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build quota summary for API responses."""
    settings = get_settings()
    cfg = source_config or {}
    from_source = cfg.get("account_points") is not None
    from_override = cfg.get("max_calls_per_minute") is not None
    account_points = resolve_account_points(source_config)
    max_calls = resolve_max_calls_per_minute(source_config)
    return {
        "account_points": account_points,
        "max_calls_per_minute": max_calls,
        "tier_max_calls_per_minute": points_to_max_calls_per_minute(account_points),
        "account_points_from_source": from_source,
        "max_calls_from_override": from_override,
        "env_account_points": settings.tushare_account_points,
    }
