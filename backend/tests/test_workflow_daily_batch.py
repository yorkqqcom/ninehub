"""Workflow daily batch collect tests."""

from datetime import date, datetime, timezone

import pytest

from app.models.workflow import NodeRun, Workflow, WorkflowRun
from app.catalog.tia_probe_registry import last_trading_day
from app.services.workflow.collect_profile import build_workflow_collect_profile
from app.services.workflow.collect_batch import (
    DAILY_BATCH_MODE_OVERRIDES,
    DAILY_MAX_API_CALLS,
    DAILY_RECENT_PERIODS,
    resolve_batch_mode,
    resolve_daily_max_codes,
    resolve_run_batch_mode,
    resolve_workflow_collect_config,
    resolve_workflow_collect_dates,
    resolve_workflow_sync_profile,
)


def test_resolve_run_batch_mode() -> None:
    assert resolve_run_batch_mode("cron") == "daily"
    assert resolve_run_batch_mode("manual") == "daily"
    assert resolve_run_batch_mode("backfill") == "backfill"
    assert resolve_run_batch_mode("unknown") is None


def test_resolve_daily_max_codes_respects_budget() -> None:
    assert resolve_daily_max_codes("daily_basic", "trade_date") == 5000
    assert resolve_daily_max_codes("stk_managers", "ts_code") == 200
    assert resolve_daily_max_codes("stk_holdertrade", "date_range") == 100
    assert resolve_daily_max_codes("income", "period") == DAILY_MAX_API_CALLS // DAILY_RECENT_PERIODS
    assert resolve_daily_max_codes("disclosure_date", "period") == 0


def test_daily_collect_config_caps_stale_schema_max_codes() -> None:
    stale = {"collect": {"max_codes_per_run": 5000, "max_api_calls_per_run": 200}}
    profile = resolve_workflow_sync_profile("stk_managers", stale, batch_mode="daily")
    config = resolve_workflow_collect_config(
        stale, profile, batch_mode="daily", api_name="stk_managers"
    )
    assert profile.max_codes_per_run == 200
    assert config.max_codes_per_run == 200
    assert config.max_api_calls_per_run == DAILY_MAX_API_CALLS


def test_daily_period_collect_config_fits_two_period_budget() -> None:
    profile = resolve_workflow_sync_profile("income", {}, batch_mode="daily")
    config = resolve_workflow_collect_config({}, profile, batch_mode="daily", api_name="income")
    assert config.max_codes_per_run == 100
    assert config.max_codes_per_run * DAILY_RECENT_PERIODS <= DAILY_MAX_API_CALLS


def test_resolve_batch_mode_defaults() -> None:
    assert resolve_batch_mode("cron") == "daily"
    assert resolve_batch_mode("manual") == "daily"
    assert resolve_batch_mode("manual", explicit="backfill") == "backfill"
    assert resolve_batch_mode("backfill") == "backfill"


def test_daily_mode_overrides_trade_date_for_daily_basic() -> None:
    profile = resolve_workflow_sync_profile("daily_basic", {"collect": {"mode": "generic"}}, batch_mode="daily")
    assert profile.mode == "trade_date"
    assert profile.max_api_calls_per_run == 200


def test_backfill_mode_overrides_daily_to_trade_date() -> None:
    schema = {"collect": {"mode": "date_range", "max_codes_per_run": 50}}
    profile = resolve_workflow_sync_profile("daily", schema, batch_mode="backfill")
    assert profile.mode == "trade_date"
    assert profile.max_api_calls_per_run == 200


def test_backfill_top10_holders_uses_date_range() -> None:
    profile = resolve_workflow_sync_profile("top10_holders", {}, batch_mode="backfill")
    assert profile.mode == "date_range"


def test_backfill_repurchase_uses_exchange_date_range() -> None:
    profile = resolve_workflow_sync_profile("repurchase", {}, batch_mode="backfill")
    assert profile.mode == "exchange_date_range"


def test_backfill_disclosure_date_uses_period() -> None:
    profile = resolve_workflow_sync_profile("disclosure_date", {}, batch_mode="backfill")
    assert profile.mode == "period"


def test_daily_mode_snapshot_for_stock_basic() -> None:
    profile = resolve_workflow_sync_profile("stock_basic", {}, batch_mode="daily")
    assert profile.mode == "snapshot"


@pytest.mark.asyncio
async def test_resolve_workflow_collect_dates_incremental(db_session) -> None:
    workflow = Workflow(name="wf", status="published")
    db_session.add(workflow)
    await db_session.flush()

    prev_run = WorkflowRun(
        workflow_id=workflow.id,
        status="success",
        trigger_type="cron",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db_session.add(prev_run)
    await db_session.flush()

    db_session.add(
        NodeRun(
            workflow_run_id=prev_run.id,
            node_id="collect-daily_basic",
            node_type="collect",
            status="success",
            result_json={"collect_end_date": "2026-06-10"},
        )
    )
    await db_session.flush()

    def _resolve(sync_session):
        return resolve_workflow_collect_dates(
            sync_session,
            workflow_id=workflow.id,
            node_id="collect-daily_basic",
            mode="trade_date",
            batch_mode="daily",
            global_start_str="2010-01-01",
        )

    start, end = await db_session.run_sync(lambda s: _resolve(s))
    assert start == date(2026, 6, 11)
    assert end == last_trading_day(date.today())


def test_resolve_rotation_codes_holdertrade() -> None:
    from app.services.workflow.collect_batch import resolve_rotation_codes

    assert resolve_rotation_codes("stk_holdertrade") == 100
    assert resolve_rotation_codes("daily") == 200


def test_all_workflow_apis_have_daily_mode() -> None:
    assert len(DAILY_BATCH_MODE_OVERRIDES) == 32


def test_build_workflow_collect_profile_caps_stored_max_codes() -> None:
    stale = {"collect": {"max_codes_per_run": 5000}}
    profile = build_workflow_collect_profile("stk_managers", stale, batch_mode="daily")
    assert profile["max_codes_stored"] == 5000
    assert profile["max_codes_effective"] == 200
    assert profile["rotation_enabled"] is True
    assert any("override" in note for note in profile["notes"])
