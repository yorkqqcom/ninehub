"""Celery application."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ninehub",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    include=[
        "app.tasks.sync_tasks",
        "app.tasks.workflow_tasks",
        "app.tasks.tia_tasks",
        "app.tasks.maintenance_tasks",
        "app.tasks.quality_tasks",
        "app.tasks.platform_jobs",
        "app.tasks.backtest_tasks",
        "app.tasks.browser_tasks",
    ],
    beat_schedule={
        "dispatch-scheduled-tasks": {
            "task": "ninehub.dispatch_scheduled_tasks",
            "schedule": 60.0,
        },
        "run-daily-quality": {
            "task": "ninehub.run_quality_check",
            "schedule": crontab(hour=18, minute=0),
        },
        "cleanup-export-files": {
            "task": "ninehub.cleanup_export_files",
            "schedule": crontab(hour=3, minute=0),
        },
        "cleanup-watch-alerts": {
            "task": "ninehub.cleanup_watch_alerts",
            "schedule": crontab(hour=3, minute=15),
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"])


from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def init_worker_tia_runtime(**kwargs) -> None:
    from app.sync.bootstrap import bootstrap_tia_runtime

    bootstrap_tia_runtime()
