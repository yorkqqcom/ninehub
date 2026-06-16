"""Data quality endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import RequireAdmin, get_current_user
from app.models.user import User
from app.schemas.quality import (
    QualityReportPageResponse,
    QualityRuleCreate,
    QualityRulePageResponse,
    QualityRuleResponse,
    QualityRuleUpdate,
    QualityRunRequest,
    QualityRunResponse,
)
from app.services.platform.job_service import PlatformJobService
from app.services.quality.service import QualityService
from app.tasks.dispatch import dispatch_task
from app.tasks.quality_tasks import run_quality_check_task

router = APIRouter()
_service = QualityService()
_jobs = PlatformJobService()


@router.get(
    "/rules",
    response_model=QualityRulePageResponse,
    summary="质检规则列表",
    description="分页列出 quality_rules，支持按 data_type 筛选。",
)
async def list_rules(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    target_data_type: Optional[str] = Query(None),
) -> QualityRulePageResponse:
    return await _service.list_rules(
        session, skip=skip, limit=limit, target_data_type=target_data_type
    )


@router.post(
    "/rules",
    response_model=QualityRuleResponse,
    summary="创建质检规则",
)
async def create_rule(
    body: QualityRuleCreate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> QualityRuleResponse:
    result = await _service.create_rule(session, body)
    await session.commit()
    return result


@router.patch(
    "/rules/{rule_id}",
    response_model=QualityRuleResponse,
    summary="更新质检规则",
)
async def update_rule(
    rule_id: int,
    body: QualityRuleUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> QualityRuleResponse:
    result = await _service.update_rule(session, rule_id, body)
    await session.commit()
    return result


@router.get(
    "/reports",
    response_model=QualityReportPageResponse,
    summary="质检报告列表",
    description="分页查询 quality_reports，支持按代码、类型、状态筛选。",
)
async def list_reports(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    data_type: Optional[str] = Query(None),
    stock_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
) -> QualityReportPageResponse:
    return await _service.list_reports(
        session,
        skip=skip,
        limit=limit,
        data_type=data_type,
        stock_code=stock_code,
        status=status,
    )


@router.post(
    "/run",
    response_model=QualityRunResponse,
    summary="触发质检",
    description="admin 触发同步或异步质检任务。",
)
async def run_quality(
    body: QualityRunRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
) -> QualityRunResponse:
    if body.async_mode:
        job = await _jobs.create(session, "quality_check", created_by_id=current_user.id)
        job.result_json = {
            "params": {"data_type": body.data_type, "stock_code": body.stock_code},
        }
        await session.flush()
        job_id = job.id
        await session.commit()
        dispatch_task(run_quality_check_task, body.data_type, body.stock_code, job_id)
        return QualityRunResponse(
            reports_created=0,
            message="质检任务已提交",
            job_id=job_id,
        )
    result = await _service.run_check(session, data_type=body.data_type, stock_code=body.stock_code)
    await session.commit()
    return result
