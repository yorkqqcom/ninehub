"""Platform long-running job tasks."""

from app.tasks.celery_app import celery_app


@celery_app.task(name="ninehub.run_platform_job")
def run_platform_job(job_id: int) -> dict:
    """Execute platform job with progress updates to platform_jobs table."""
    return {"job_id": job_id, "status": "not_implemented"}
