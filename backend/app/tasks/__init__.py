"""Celery task modules (imported for worker registration)."""

from app.tasks import (  # noqa: F401
    maintenance_tasks,
    platform_jobs,
    quality_tasks,
    sync_tasks,
    tia_tasks,
    workflow_tasks,
)
