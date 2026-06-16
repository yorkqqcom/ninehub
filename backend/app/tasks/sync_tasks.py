"""Sync and dispatch Celery tasks."""

from app.core.database import SyncSessionLocal
from app.models.task_run import TaskRun
from app.services.tasks.run_service import TaskRunService
from app.services.workflow.scheduler import WorkflowSchedulerService
from app.tasks.celery_app import celery_app


def _mark_run_failed(session, run_id: int | None, error: str) -> None:
    if run_id is None:
        return
    run = session.get(TaskRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.error = error
    run.message = error[:500] if error else "Collect failed"
    session.commit()


@celery_app.task(name="ninehub.run_collect")
def run_collect(task_id: int, run_id: int | None = None) -> dict:
    """Execute a sync task; logs to task_runs when run_id provided."""
    service = TaskRunService()
    session = SyncSessionLocal()
    try:
        if run_id is None:
            run = service.create_run_sync(session, task_id)
            run_id = run.id
            session.commit()
        service.execute_run_sync(session, run_id)
        session.commit()
        return {"task_id": task_id, "run_id": run_id, "status": "success"}
    except Exception as exc:
        session.rollback()
        try:
            _mark_run_failed(session, run_id, str(exc))
        except Exception:
            session.rollback()
        return {"task_id": task_id, "run_id": run_id, "status": "failed", "error": str(exc)}
    finally:
        session.close()


@celery_app.task(name="ninehub.dispatch_scheduled_tasks")
def dispatch_scheduled_tasks() -> dict:
    """Beat: scan sync_tasks + published workflow crons on trading days."""
    session = SyncSessionLocal()
    try:
        from app.services.tasks.scheduler import TaskSchedulerService

        task_result = TaskSchedulerService().dispatch_due(session)
        wf_result = WorkflowSchedulerService().dispatch_due(session)
        return {
            "tasks": task_result,
            "workflows": wf_result,
            "dispatched": task_result.get("dispatched", 0) + wf_result.get("dispatched", 0),
        }
    finally:
        session.close()
