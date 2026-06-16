"""Workflow daily batch — incremental dates, modes, and collect budgets."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.catalog.tia_probe_registry import last_trading_day
from app.models.workflow import NodeRun, WorkflowRun
from app.services.tia.collect_pattern import resolve_collect_pattern
from app.services.tia.sync_profiles import SyncProfile, profile_for_pattern, resolve_sync_profile
from app.sync.tia_collect.config import CollectConfig, resolve_collect_config

# Daily catch-up when no prior successful node run exists.
DEFAULT_CATCHUP_TRADING_DAYS = 5

# 2400-point account: 200 calls/min — one workflow node stays within one minute budget.
DAILY_MAX_API_CALLS = 200
DAILY_MAX_CODES = 5000
# Per-code APIs rotated daily (ts_code / period / weekly date_range).
DAILY_ROTATION_CODES = 200

# APIs whose publisher lags T+0 (use previous trading day in daily batch).
TRADE_DATE_PUBLISH_LAG: dict[str, int] = {
    "margin": 1,
}

# Prefer trade_date (full market per day) for these APIs in daily batch.
DAILY_BATCH_MODE_OVERRIDES: dict[str, str] = {
    "stock_basic": "snapshot",
    "bse_mapping": "snapshot",
    "new_share": "snapshot",
    "daily_basic": "trade_date",
    "adj_factor": "trade_date",
    "stk_limit": "trade_date",
    "margin": "trade_date",
    "margin_secs": "trade_date",
    "block_trade": "trade_date",
    "top_list": "trade_date",
    "income": "period",
    "balancesheet": "period",
    "cashflow": "period",
    "express": "period",
    "forecast": "period",
    "fina_indicator": "period",
    "fina_mainbz": "period",
    "disclosure_date": "ts_code",
    "stock_company": "ts_code",
    "top10_holders": "ts_code",
    "top10_floatholders": "ts_code",
    "stk_holdernumber": "ts_code",
    "stk_managers": "ts_code",
    "stk_rewards": "ts_code",
    "stk_holdertrade": "ts_code",
    "pledge_stat": "ts_code",
    "pledge_detail": "ts_code",
    "dividend": "ts_code",
    "repurchase": "ts_code",
    "hk_hold": "date_range",
    "weekly": "date_range",
}


def resolve_batch_mode(trigger_type: str, *, explicit: str | None = None) -> str:
    if explicit in ("daily", "backfill"):
        return explicit
    if trigger_type == "backfill":
        return "backfill"
    return "daily"


def _daily_max_codes(api_name: str, mode: str) -> int:
    if mode == "snapshot" or mode == "trade_date":
        return DAILY_MAX_CODES
    if mode in ("ts_code", "period", "date_range"):
        return DAILY_ROTATION_CODES
    return DAILY_MAX_API_CALLS


def resolve_workflow_sync_profile(
    api_name: str,
    schema: dict | None,
    *,
    batch_mode: str,
) -> SyncProfile:
    """Resolve collect mode for workflow runs; daily batch overrides probe/generic misconfig."""
    if batch_mode == "daily" and api_name in DAILY_BATCH_MODE_OVERRIDES:
        mode = DAILY_BATCH_MODE_OVERRIDES[api_name]
        base = profile_for_pattern(mode)
        collect = (schema or {}).get("collect") or {}
        return SyncProfile(
            mode=mode,
            schedule_cron=base.schedule_cron,
            auto_activate=base.auto_activate,
            trigger_initial=base.trigger_initial,
            label=base.label,
            max_codes_per_run=int(collect.get("max_codes_per_run", _daily_max_codes(api_name, mode))),
            max_api_calls_per_run=int(
                collect.get("max_api_calls_per_run", DAILY_MAX_API_CALLS)
            ),
        )

    profile = resolve_sync_profile(api_name, schema)
    if batch_mode == "daily" and profile.mode in ("generic", "date_range"):
        inferred = resolve_collect_pattern(api_name)
        if inferred.mode not in ("generic",):
            base = profile_for_pattern(inferred.pattern_key)
            collect = (schema or {}).get("collect") or {}
            return SyncProfile(
                mode=inferred.mode,
                schedule_cron=base.schedule_cron,
                auto_activate=base.auto_activate,
                trigger_initial=base.trigger_initial,
                label=base.label,
                max_codes_per_run=int(
                    collect.get("max_codes_per_run", _daily_max_codes(api_name, inferred.mode))
                ),
                max_api_calls_per_run=int(
                    collect.get("max_api_calls_per_run", DAILY_MAX_API_CALLS)
                ),
            )
    return profile


def resolve_workflow_collect_config(
    schema: dict | None,
    profile: SyncProfile,
    *,
    batch_mode: str,
) -> CollectConfig:
    if batch_mode == "backfill":
        return resolve_collect_config(schema or {}, profile)
    collect = (schema or {}).get("collect") or {}
    return CollectConfig(
        max_codes_per_run=int(collect.get("max_codes_per_run", DAILY_MAX_CODES)),
        max_api_calls_per_run=int(
            collect.get("max_api_calls_per_run", DAILY_MAX_API_CALLS)
        ),
        batch_size=max(1, int(collect.get("batch_size", 1))),
    )


def _trading_days_before(end: date, count: int) -> date:
    cursor = end
    seen = 0
    while seen < count:
        if cursor.weekday() < 5:
            from app.services.trading_calendar.service import CN_HOLIDAYS

            if cursor not in CN_HOLIDAYS:
                seen += 1
                if seen >= count:
                    return cursor
        cursor -= timedelta(days=1)
    return cursor


def get_last_successful_node_run(
    session: Session,
    workflow_id: int,
    node_id: str,
) -> NodeRun | None:
    return _last_successful_node_run(session, workflow_id, node_id)


def _last_successful_node_run(
    session: Session,
    workflow_id: int,
    node_id: str,
) -> NodeRun | None:
    stmt = (
        select(NodeRun)
        .join(WorkflowRun, WorkflowRun.id == NodeRun.workflow_run_id)
        .where(
            WorkflowRun.workflow_id == workflow_id,
            NodeRun.node_id == node_id,
            NodeRun.status == "success",
            or_(NodeRun.result_json.isnot(None), NodeRun.message.isnot(None)),
        )
        .order_by(NodeRun.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _trading_day_offset(ref: date, trading_days_back: int) -> date:
    cursor = ref
    remaining = trading_days_back
    while remaining > 0:
        cursor -= timedelta(days=1)
        from app.services.trading_calendar.service import CN_HOLIDAYS

        if cursor.weekday() < 5 and cursor not in CN_HOLIDAYS:
            remaining -= 1
    return cursor


def resolve_workflow_collect_dates(
    session: Session,
    *,
    workflow_id: int,
    node_id: str,
    mode: str,
    batch_mode: str,
    global_start_str: str,
    api_name: str | None = None,
) -> tuple[date, date]:
    """Incremental date window for workflow collect nodes."""
    end = last_trading_day(date.today())
    if batch_mode == "daily" and api_name and api_name in TRADE_DATE_PUBLISH_LAG:
        end = _trading_day_offset(end, TRADE_DATE_PUBLISH_LAG[api_name])
    global_floor = date.fromisoformat(global_start_str)

    if mode == "snapshot":
        return end, end

    if batch_mode == "backfill":
        start = global_floor
        return (end, end) if start > end else (start, end)

    last = _last_successful_node_run(session, workflow_id, node_id)
    if last and last.result_json:
        prev_end = last.result_json.get("collect_end_date")
        if prev_end:
            start = date.fromisoformat(str(prev_end)) + timedelta(days=1)
        else:
            start = _trading_days_before(last_trading_day(end), DEFAULT_CATCHUP_TRADING_DAYS)
    else:
        start = _trading_days_before(last_trading_day(end), DEFAULT_CATCHUP_TRADING_DAYS)

    start = max(start, global_floor)
    if start > end:
        start = end
    return start, end


def extract_node_detail_json(
    collect_result_detail: dict | None,
    *,
    batch_mode: str,
    start_date: date,
    end_date: date,
) -> dict:
    detail = dict(collect_result_detail or {})
    detail["batch_mode"] = batch_mode
    detail["collect_start_date"] = start_date.isoformat()
    detail["collect_end_date"] = end_date.isoformat()
    return detail
