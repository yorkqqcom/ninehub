"""Sync task Cron dispatch (D-06/D-08)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.sync_task import SyncTask
from app.services.trading_calendar.service import TradingCalendarService
from app.services.tushare.quota import estimate_sync_api_calls
from app.services.workflow.scheduler import cron_matches, next_cron_run


class TaskSchedulerService:
    def __init__(self) -> None:
        self._calendar = TradingCalendarService()

    def dispatch_due(self, session: Session, *, now: datetime | None = None) -> dict:
        """Beat: trigger active sync_tasks whose cron matches current minute."""
        current = now or datetime.now(timezone.utc)
        local = current.astimezone(timezone(timedelta(hours=8)))
        ok, reason = self._calendar.is_trading_day(local.date())
        if not ok:
            return {"dispatched": 0, "reason": reason}

        tasks = session.execute(
            select(SyncTask).where(
                SyncTask.status == "active",
                SyncTask.schedule_cron.isnot(None),
            )
        ).scalars().all()

        stagger = get_settings().tushare_dispatch_stagger_seconds
        dispatched = 0
        for task in tasks:
            if task.schedule_cron is None:
                continue
            if task.next_run_at and task.next_run_at > current:
                continue
            if not cron_matches(task.schedule_cron, local):
                continue
            try:
                from app.tasks.dispatch import dispatch_task
                from app.tasks.sync_tasks import run_collect

                if dispatched > 0 and stagger > 0:
                    time.sleep(stagger)
                dispatch_task(run_collect, task.id)
                task.next_run_at = next_cron_run(task.schedule_cron, local).astimezone(
                    timezone.utc
                )
                session.commit()
                dispatched += 1
            except Exception:
                session.rollback()

        return {
            "dispatched": dispatched,
            "estimated_calls": sum(
                estimate_sync_api_calls(t.data_type) for t in tasks if t.status == "active"
            ),
        }
