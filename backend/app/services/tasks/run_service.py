"""Task run logging and SyncExecutor integration."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.sync_task import SyncTask
from app.models.task_run import TaskRun
from app.schemas.task_run import TaskRunPageResponse, TaskRunResponse, TaskRunTriggerResponse
from app.services.platform.service import PlatformService
from app.services.tia.credentials import (
    require_tushare_token,
    resolve_tushare_collect_credentials,
)
from app.services.tia.credentials_tdx import (
    build_sync_auth_extra,
    resolve_collect_source_credentials,
)
from app.services.tushare.quota import validate_points_for_data_type
from app.services.tushare.source_quota import resolve_max_calls_per_minute
from app.sync.executor import SyncExecutor
from app.sync.handlers import CollectResult, SyncContext


class TaskRunService:
    async def create_run(
        self,
        session: AsyncSession,
        task_id: int,
        trigger_type: str = "manual",
    ) -> TaskRun:
        task = await session.get(SyncTask, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        run = TaskRun(task_id=task_id, status="pending", trigger_type=trigger_type)
        session.add(run)
        await session.flush()
        return run

    def create_run_sync(
        self,
        session: Session,
        task_id: int,
        trigger_type: str = "manual",
    ) -> TaskRun:
        task = session.get(SyncTask, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        run = TaskRun(task_id=task_id, status="pending", trigger_type=trigger_type)
        session.add(run)
        session.flush()
        return run

    def _check_upstream_sync(self, session: Session, task: SyncTask) -> None:
        if task.upstream_task_id is None:
            return
        last_run = session.execute(
            select(TaskRun)
            .where(TaskRun.task_id == task.upstream_task_id)
            .order_by(TaskRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_run is None or last_run.status != "success":
            raise ValidationError(
                f"上游任务 {task.upstream_task_id} 尚未成功完成",
                details={"upstream_task_id": task.upstream_task_id},
            )

    def _resolve_source_sync(
        self,
        session: Session,
        source_id: int | None,
        data_type: str | None = None,
    ) -> tuple[str, str, dict, int | None]:
        creds = resolve_collect_source_credentials(session, source_id, data_type=data_type)
        provider = str(creds.get("provider") or "tushare")
        if provider == "tdx":
            return (
                provider,
                "",
                dict(creds.get("source_config") or creds),
                creds.get("source_id"),
            )
        token = require_tushare_token(creds)
        return (
            provider,
            token,
            dict(creds.get("source_config") or {}),
            creds.get("source_id"),
        )

    @staticmethod
    def _is_failed_collect(result: CollectResult) -> bool:
        if result.rows_upserted > 0:
            return False
        msg = (result.message or "").strip().lower()
        if result.api_calls > 0 and (
            "落库 0 行" in (result.message or "")
            or "upserted 0 rows" in msg
            or "empty response" in msg
        ):
            return True
        if result.api_calls > 0:
            return False
        if not msg:
            return True
        markers = ("not configured", "no table_name", "failed", "error")
        return any(m in msg for m in markers)

    def execute_run_sync(self, session: Session, run_id: int) -> TaskRun:
        run = session.get(TaskRun, run_id)
        if run is None:
            raise NotFoundError(f"Task run {run_id} not found")
        task = session.get(SyncTask, run.task_id)
        if task is None:
            raise NotFoundError(f"Task {run.task_id} not found")

        self._check_upstream_sync(session, task)

        try:
            provider, token, source_config, resolved_source_id = self._resolve_source_sync(
                session, task.source_id, task.data_type
            )
            if task.source_id is None and resolved_source_id is not None:
                task.source_id = resolved_source_id
                session.flush()
            validate_points_for_data_type(
                task.data_type,
                provider=provider,
                source_config=source_config,
            )

            start_str = PlatformService().resolve_sync_start_date_sync(session, task.data_type)
            start_date, end_date = self._resolve_collect_dates(session, task, start_str)

            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            run.message = f"Collect started ({task.data_type})"
            session.flush()

            from app.catalog.registry import get_data_type_entry

            entry = get_data_type_entry(task.data_type)
            ctx = SyncContext(
                data_type=task.data_type,
                source_id=task.source_id or 0,
                start_date=start_date,
                end_date=end_date,
                extra=build_sync_auth_extra(
                    {
                        "provider": provider,
                        "base_url": source_config.get("base_url"),
                        "api_token": source_config.get("api_token"),
                        "source_config": source_config,
                    },
                    {
                        "session": session,
                        "token": token,
                        "source_config": source_config,
                        "max_calls_per_minute": resolve_max_calls_per_minute(source_config),
                        "table_name": entry.table_name if entry else None,
                        "collect_params": task.collect_params or {},
                    },
                ),
            )
            result = SyncExecutor().run(ctx)
            if self._is_failed_collect(result):
                raise ValidationError(result.message or "Collect returned no data")
            run.rows_upserted = result.rows_upserted
            run.status = "success"
            run.message = result.message or f"Upserted {result.rows_upserted} rows"
            run.result_json = {
                "collect_start_date": start_date.isoformat(),
                "collect_end_date": end_date.isoformat(),
                "api_calls": result.api_calls,
                **(result.detail_json or {}),
            }
            run.finished_at = datetime.now(timezone.utc)
            session.flush()
            return run
        except Exception as exc:
            session.rollback()
            run = session.get(TaskRun, run_id)
            if run is None:
                raise NotFoundError(f"Task run {run_id} not found") from exc
            run.status = "failed"
            run.error = str(exc)
            run.message = str(exc)[:500] if str(exc) else "Collect failed"
            run.finished_at = datetime.now(timezone.utc)
            session.flush()
            raise

    def _resolve_collect_dates(
        self,
        session: Session,
        task: SyncTask,
        global_start_str: str,
    ) -> tuple[date, date]:
        start_date = date.fromisoformat(global_start_str)
        end_date = date.today()
        last_run = session.execute(
            select(TaskRun)
            .where(
                TaskRun.task_id == task.id,
                TaskRun.status == "success",
                or_(TaskRun.rows_upserted.is_(None), TaskRun.rows_upserted > 0),
            )
            .order_by(TaskRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_run and last_run.result_json:
            prev_end = last_run.result_json.get("collect_end_date")
            if prev_end:
                incremental = date.fromisoformat(str(prev_end)) + timedelta(days=1)
                if incremental > start_date:
                    start_date = incremental
        if start_date > end_date:
            start_date = end_date
        return start_date, end_date

    async def list_runs(
        self,
        session: AsyncSession,
        task_id: int,
        skip: int = 0,
        limit: int = 50,
    ) -> TaskRunPageResponse:
        base = select(TaskRun).where(TaskRun.task_id == task_id)
        total = (await session.execute(
            select(func.count()).select_from(TaskRun).where(TaskRun.task_id == task_id)
        )).scalar_one()
        result = await session.execute(
            base.order_by(TaskRun.id.desc()).offset(skip).limit(limit)
        )
        runs = result.scalars().all()
        page = (skip // limit) + 1 if limit else 1
        return TaskRunPageResponse(
            items=[TaskRunResponse.model_validate(r) for r in runs],
            total=total,
            page=page,
            size=limit,
        )

    async def trigger(
        self,
        session: AsyncSession,
        task_id: int,
    ) -> TaskRunTriggerResponse:
        run = await self.create_run(session, task_id)
        await session.commit()
        from app.tasks.dispatch import dispatch_task
        from app.tasks.sync_tasks import run_collect

        dispatch_task(run_collect, task_id, run.id)
        return TaskRunTriggerResponse(run_id=run.id, message="Task run queued")
