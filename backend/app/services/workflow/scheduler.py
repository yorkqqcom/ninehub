"""Workflow Cron dispatch (E-06)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.trading_calendar.service import TradingCalendarService
from app.services.workflow.service import WorkflowService


def _field_matches(part: str, value: int) -> bool:
    if part == "*":
        return True
    for segment in part.split(","):
        if "-" in segment:
            start, end = segment.split("-", 1)
            if int(start) <= value <= int(end):
                return True
        elif int(segment) == value:
            return True
    return False


def cron_matches(expression: str, dt: datetime) -> bool:
    """Match 5-field cron: minute hour dom month dow (0=Sun dow)."""
    parts = expression.strip().split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    # Python weekday: Mon=0; cron dow: Sun=0
    cron_dow = (dt.weekday() + 1) % 7
    return (
        _field_matches(minute, dt.minute)
        and _field_matches(hour, dt.hour)
        and _field_matches(dom, dt.day)
        and _field_matches(month, dt.month)
        and _field_matches(dow, cron_dow)
    )


def next_cron_run(expression: str, after: datetime) -> datetime:
    """Find next minute-aligned run after `after` (Asia/Shanghai naive → UTC)."""
    cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 8):
        if cron_matches(expression, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    return cursor


class WorkflowSchedulerService:
    def __init__(self) -> None:
        self._workflow_service = WorkflowService()
        self._calendar = TradingCalendarService()

    def dispatch_due(self, session: Session, *, now: datetime | None = None) -> dict:
        """Beat: trigger published workflows whose cron matches current minute."""
        current = now or datetime.now(timezone.utc)
        local = current.astimezone(timezone(timedelta(hours=8)))
        ok, _ = self._calendar.is_trading_day(local.date())
        if not ok:
            return {"dispatched": 0, "reason": "non_trading_day"}

        workflows = session.execute(
            select(Workflow).where(
                Workflow.status == "published",
                Workflow.schedule_cron.isnot(None),
            )
        ).scalars().all()

        dispatched = 0
        for wf in workflows:
            if wf.schedule_cron is None:
                continue
            if wf.next_run_at and wf.next_run_at > current:
                continue
            if not cron_matches(wf.schedule_cron, local):
                continue
            try:
                self._workflow_service.trigger_run_sync(
                    session,
                    wf.id,
                    trigger_type="cron",
                    skip_gates=False,
                )
                wf.next_run_at = next_cron_run(wf.schedule_cron, local).astimezone(timezone.utc)
                session.commit()
                dispatched += 1
            except Exception:
                session.rollback()
        return {"dispatched": dispatched}
