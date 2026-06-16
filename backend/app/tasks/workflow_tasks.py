"""Workflow Celery tasks."""

from app.core.database import SyncSessionLocal
from app.services.workflow.executor import WorkflowExecutor
from app.tasks.celery_app import celery_app


@celery_app.task(name="ninehub.run_workflow")
def run_workflow(run_id: int, skip_gates: bool = False) -> dict:
    """Execute workflow DAG in Celery worker."""
    executor = WorkflowExecutor()
    session = SyncSessionLocal()
    try:
        run = executor.execute_sync(session, run_id, skip_gates=skip_gates)
        session.commit()
        return {"run_id": run_id, "status": run.status}
    except Exception as exc:
        session.rollback()
        return {"run_id": run_id, "status": "failed", "error": str(exc)}
    finally:
        session.close()
