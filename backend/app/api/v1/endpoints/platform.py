"""Platform configuration and jobs."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import RequireAdmin, get_current_user
from app.models.platform_job import PlatformJob
from app.models.user import User
from app.schemas.common import HealthResponse, JobStatusResponse
from app.schemas.platform import PlatformSettingsResponse, PlatformSettingsUpdate
from app.services.platform.service import PlatformService

router = APIRouter()
_platform = PlatformService()


@router.get(
    "/settings",
    response_model=PlatformSettingsResponse,
    summary="平台配置",
    description="全局 sync_start_date 及按 data_type 覆盖。",
)
async def get_settings(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> PlatformSettingsResponse:
    return await _platform.get_settings(session)


@router.put(
    "/settings",
    response_model=PlatformSettingsResponse,
    summary="更新平台配置",
)
async def update_settings(
    body: PlatformSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> PlatformSettingsResponse:
    result = await _platform.update_settings(session, body)
    await session.commit()
    return result


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="长任务进度",
    description="TIA 扫描/审计等 Job 进度查询。",
)
async def get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JobStatusResponse:
    result = await session.execute(select(PlatformJob).where(PlatformJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_type != "workflow_run":
        if current_user.role != "admin" and job.created_by_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
    return JobStatusResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        message=job.message,
        error=job.error,
    )


health_router = APIRouter()


@health_router.get("/health", response_model=HealthResponse, summary="健康检查")
async def health() -> HealthResponse:
    return HealthResponse(app="NineHub")
