"""Platform job lifecycle service."""

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.platform_job import PlatformJob


class PlatformJobService:
    async def create(
        self,
        session: AsyncSession,
        job_type: str,
        created_by_id: Optional[int] = None,
    ) -> PlatformJob:
        job = PlatformJob(
            job_type=job_type,
            status="pending",
            progress=0,
            message="Queued",
            created_by_id=created_by_id,
        )
        session.add(job)
        await session.flush()
        return job

    async def get(self, session: AsyncSession, job_id: int) -> PlatformJob:
        result = await session.execute(select(PlatformJob).where(PlatformJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    async def update(
        self,
        session: AsyncSession,
        job_id: int,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result_json: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> PlatformJob:
        job = await self.get(session, job_id)
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message
        if result_json is not None:
            job.result_json = result_json
        if error is not None:
            job.error = error
        await session.flush()
        return job

    def create_sync(
        self,
        session: Session,
        job_type: str,
        created_by_id: Optional[int] = None,
    ) -> PlatformJob:
        job = PlatformJob(
            job_type=job_type,
            status="pending",
            progress=0,
            message="Queued",
            created_by_id=created_by_id,
        )
        session.add(job)
        session.flush()
        return job

    def update_sync(
        self,
        session: Session,
        job_id: int,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result_json: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> PlatformJob:
        job = session.get(PlatformJob, job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message
        if result_json is not None:
            job.result_json = result_json
        if error is not None:
            job.error = error
        session.flush()
        return job
