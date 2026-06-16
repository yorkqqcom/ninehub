"""Workflow daily batch collect tests."""

from datetime import date, datetime, timezone

import pytest

from app.models.workflow import NodeRun, Workflow, WorkflowRun
from app.services.workflow.collect_batch import (
    DAILY_BATCH_MODE_OVERRIDES,
    resolve_batch_mode,
    resolve_workflow_collect_dates,
    resolve_workflow_sync_profile,
)


def test_resolve_batch_mode_defaults() -> None:
    assert resolve_batch_mode("cron") == "daily"
    assert resolve_batch_mode("manual") == "daily"
    assert resolve_batch_mode("manual", explicit="backfill") == "backfill"
    assert resolve_batch_mode("backfill") == "backfill"


def test_daily_mode_overrides_trade_date_for_daily_basic() -> None:
    profile = resolve_workflow_sync_profile("daily_basic", {"collect": {"mode": "generic"}}, batch_mode="daily")
    assert profile.mode == "trade_date"
    assert profile.max_api_calls_per_run == 200


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
    assert end == date.today()


def test_all_workflow_apis_have_daily_mode() -> None:
    assert len(DAILY_BATCH_MODE_OVERRIDES) == 31
