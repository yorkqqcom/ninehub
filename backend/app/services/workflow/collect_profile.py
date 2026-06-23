"""Workflow collect profile — effective daily/backfill strategy for UI (read-only)."""

from __future__ import annotations

from typing import Any

from app.services.workflow.collect_batch import (
    DAILY_RECENT_PERIODS,
    TRADE_DATE_PUBLISH_LAG,
    resolve_rotation_codes,
    resolve_workflow_collect_config,
    resolve_workflow_sync_profile,
)
from app.sync.tia_collect.period import PERIOD_MARKET_APIS


def build_workflow_collect_profile(
    api_name: str,
    schema: dict | None,
    *,
    batch_mode: str = "daily",
) -> dict[str, Any]:
    """Return platform-effective collect settings for workflow / TIA UI."""
    profile = resolve_workflow_sync_profile(api_name, schema, batch_mode=batch_mode)
    config = resolve_workflow_collect_config(
        schema, profile, batch_mode=batch_mode, api_name=api_name
    )
    collect = (schema or {}).get("collect") or {}
    stored_raw = collect.get("max_codes_per_run")
    stored_max = int(stored_raw) if stored_raw is not None else None

    mode = profile.mode
    market_period = mode == "period" and api_name in PERIOD_MARKET_APIS
    rotation_enabled = (
        batch_mode == "daily"
        and mode in ("ts_code", "date_range", "period")
        and not market_period
    )

    notes: list[str] = []
    if stored_max is not None and stored_max > config.max_codes_per_run:
        notes.append(
            f"override 存储 max_codes={stored_max}，"
            f"工作流 {batch_mode} 生效 {config.max_codes_per_run}"
        )
    if batch_mode == "backfill" and mode in ("ts_code", "period", "date_range"):
        notes.append("大规模历史回填请用 scripts/run_backfill_history.py 分 chunk")
    if mode == "period" and batch_mode == "daily" and not market_period:
        notes.append(
            f"日批拉最近 {DAILY_RECENT_PERIODS} 个报告期，"
            f"每轮 codes×periods ≤ {config.max_api_calls_per_run}"
        )

    return {
        "api_name": api_name,
        "batch_mode": batch_mode,
        "collect_mode": mode,
        "max_codes_stored": stored_max,
        "max_codes_effective": config.max_codes_per_run,
        "max_api_calls_per_run": config.max_api_calls_per_run,
        "rotation_enabled": rotation_enabled,
        "rotation_codes_per_run": resolve_rotation_codes(api_name) if rotation_enabled else None,
        "recent_periods": DAILY_RECENT_PERIODS
        if batch_mode == "daily" and mode == "period" and not market_period
        else None,
        "publish_lag_days": TRADE_DATE_PUBLISH_LAG.get(api_name),
        "notes": notes,
    }
