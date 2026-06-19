"""Data Browser Celery tasks."""

from __future__ import annotations

import asyncio

from app.core.database import AsyncSessionLocal
from app.services.platform.job_service import PlatformJobService
from app.services.query.browser_export import BrowserExportService
from app.tasks.celery_app import celery_app


@celery_app.task(name="ninehub.run_browser_export")
def run_browser_export_task(job_id: int) -> dict:
    service = BrowserExportService()
    jobs = PlatformJobService()

    async def _run() -> dict:
        async with AsyncSessionLocal() as session:
            await jobs.update(session, job_id, status="running", progress=10, message="exporting")
            await session.commit()
            return await service.run_job_export(session, job_id)

    try:
        result = asyncio.run(_run())
        return {"job_id": job_id, "status": "success", **result}
    except Exception as exc:
        async def _fail() -> None:
            async with AsyncSessionLocal() as session:
                await jobs.update(
                    session,
                    job_id,
                    status="failed",
                    progress=100,
                    message="export failed",
                    error=str(exc),
                )
                await session.commit()

        try:
            asyncio.run(_fail())
        except Exception:
            pass
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
