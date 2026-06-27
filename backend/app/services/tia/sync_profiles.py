"""Sync task profiles by inferred collect pattern (post-L3 scheduling)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.tia.collect_pattern import (
    API_PATTERN_OVERRIDES,
    resolve_collect_pattern,
)


@dataclass(frozen=True)
class SyncProfile:
    mode: str
    schedule_cron: str | None
    auto_activate: bool = True
    trigger_initial: bool = True
    label: str = ""
    max_codes_per_run: int = 50
    max_api_calls_per_run: int = 200


_DEFAULT = SyncProfile(
    mode="generic",
    schedule_cron="0 18 * * 1-5",
    label="通用 · 工作日 18:00",
)

_BY_CATEGORY: dict[str, SyncProfile] = {
    "list_basic": SyncProfile(
        mode="snapshot",
        schedule_cron="0 8 * * 1-5",
        label="全量快照 · 工作日 08:00",
    ),
    "list_limit": SyncProfile(
        mode="snapshot",
        schedule_cron="0 8 * * 1-5",
        label="限量快照 · 工作日 08:00",
    ),
    "ts_code_date_range": SyncProfile(
        mode="date_range",
        schedule_cron="0 18 * * 1-5",
        label="按代码+日期 · 工作日 18:00 增量",
    ),
    "trade_date": SyncProfile(
        mode="trade_date",
        schedule_cron="0 18 * * 1-5",
        label="按交易日 · 工作日 18:00",
    ),
    "period_financial": SyncProfile(
        mode="period",
        schedule_cron="0 18 * * 5",
        label="财报期 · 每周五 18:00",
    ),
    "ts_code": SyncProfile(
        mode="ts_code",
        schedule_cron="0 18 * * 1-5",
        label="单代码 · 工作日 18:00",
    ),
    "index_daily": SyncProfile(
        mode="date_range",
        schedule_cron="0 18 * * 1-5",
        label="指数日线 · 工作日 18:00",
    ),
    "exchange_date_range": SyncProfile(
        mode="exchange_date_range",
        schedule_cron="0 8 * * 1",
        label="交易所日历 · 单次区间拉取",
    ),
    "generic": _DEFAULT,
    "file_import": SyncProfile(
        mode="file_import",
        schedule_cron="0 7 * * 1-5",
        label="TDX vipdoc · 工作日 07:00 T+1",
        max_codes_per_run=500,
        max_api_calls_per_run=500,
    ),
    "tdx_concept_snapshot": SyncProfile(
        mode="tdx_concept_snapshot",
        schedule_cron="0 7 * * 1-5",
        label="TDX 概念快照 · 工作日 07:00",
    ),
}


def profile_for_pattern(pattern_key: str) -> SyncProfile:
    return _BY_CATEGORY.get(pattern_key, _DEFAULT)


def resolve_sync_profile(api_name: str, schema: dict | None = None) -> SyncProfile:
    """Resolve sync profile from schema (post-L3) or probe param inference."""
    if schema:
        collect = schema.get("collect") or {}
        mode = collect.get("mode")
        pattern = collect.get("pattern")
        if mode:
            base = profile_for_pattern(pattern or mode)
            return SyncProfile(
                mode=mode,
                schedule_cron=base.schedule_cron,
                auto_activate=base.auto_activate,
                trigger_initial=base.trigger_initial,
                label=base.label,
                max_codes_per_run=int(
                    collect.get("max_codes_per_run", base.max_codes_per_run)
                ),
                max_api_calls_per_run=int(
                    collect.get("max_api_calls_per_run", base.max_api_calls_per_run)
                ),
            )

    if api_name in API_PATTERN_OVERRIDES:
        return profile_for_pattern(API_PATTERN_OVERRIDES[api_name])

    pattern = resolve_collect_pattern(api_name)
    return profile_for_pattern(pattern.pattern_key)
