"""Celery task registration (worker must see beat-dispatched tasks)."""

from app.tasks.celery_app import celery_app

EXPECTED_TASKS = {
    "ninehub.cleanup_export_files",
    "ninehub.dispatch_scheduled_tasks",
    "ninehub.run_backtest",
    "ninehub.run_collect",
    "ninehub.run_platform_job",
    "ninehub.run_quality_check",
    "ninehub.run_tia_activate",
    "ninehub.run_tia_doc_pages_sync",
    "ninehub.run_tia_scan",
    "ninehub.run_workflow",
}


def test_celery_registers_ninehub_tasks() -> None:
    registered = set(celery_app.tasks.keys())
    missing = EXPECTED_TASKS - registered
    assert not missing, f"Missing Celery tasks: {sorted(missing)}"
