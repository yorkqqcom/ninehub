"""Tushare points and API call estimation (F-08 / tushare-quota.mdc)."""

from typing import Any, Optional

from app.catalog.registry import get_data_type_entry
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.services.tia.scan.tushare_doc_registry import resolve_api_meta
from app.services.tushare.source_quota import resolve_account_points


def get_account_points(source_config: Optional[dict[str, Any]] = None) -> int:
    return resolve_account_points(source_config)


def api_min_points(api_name: str) -> int:
    meta = resolve_api_meta(api_name) or {}
    if meta.get("access_mode") == "standalone":
        return 0
    pts = meta.get("min_points")
    if pts is not None:
        return int(pts)
    return 120


def data_type_min_points(data_type: str) -> int:
    api = data_type.replace("tia_", "", 1) if data_type.startswith("tia_") else data_type
    if api.startswith("tushare_"):
        api = api[len("tushare_") :]
    canonical = api_min_points(api)
    entry = get_data_type_entry(data_type)
    if entry and entry.min_points:
        return max(int(entry.min_points), canonical)
    return canonical


def validate_points_for_data_type(
    data_type: str,
    *,
    provider: str = "tushare",
    source_config: Optional[dict[str, Any]] = None,
) -> None:
    if provider != "tushare":
        return
    required = data_type_min_points(data_type)
    if required <= 0:
        return
    account = resolve_account_points(source_config)
    if account < required:
        raise ValidationError(
            f"账户积分 {account} 不足，{data_type} 需要 {required} 积分",
            details={"account_points": account, "required_points": required},
        )


def estimate_sync_api_calls(data_type: str, stock_count: int = 1) -> int:
    """Rough API call estimate for dispatch stagger planning."""
    if data_type.startswith("tia_daily") or data_type.startswith("tushare_daily"):
        return max(stock_count, 1)
    return 1
