"""Sync task endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import RequireAdmin, get_current_user
from app.models.user import User
from app.schemas.catalog import DataTypeListResponse
from app.schemas.common import MessageResponse
from app.schemas.task import (
    CollectConfigResponse,
    SyncTaskCreate,
    SyncTaskPageResponse,
    SyncTaskResponse,
    SyncTaskUpdate,
)
from app.schemas.task_run import TaskRunPageResponse, TaskRunTriggerResponse
from app.services.catalog.service import CatalogService
from app.services.tasks.collect_config_service import CollectConfigService
from app.services.tasks.run_service import TaskRunService
from app.services.tasks.service import TaskService

router = APIRouter()
_task_service = TaskService()
_run_service = TaskRunService()
_catalog = CatalogService()
_collect_config = CollectConfigService()


@router.get(
    "/data-types",
    response_model=DataTypeListResponse,
    summary="任务可选数据类型",
    description="与 catalog registry 同步，供任务创建表单下拉框使用(D-07)。",
)
async def list_task_data_types(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    domain: Optional[str] = Query(None),
) -> DataTypeListResponse:
    return await _catalog.list_data_types(session, domain=domain)


@router.get(
    "",
    response_model=SyncTaskPageResponse,
    summary="采集任务列表",
    description="分页列出采集任务；data_type 标签来自 catalog。",
)
async def list_tasks(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, pattern="^(active|paused)$"),
) -> SyncTaskPageResponse:
    return await _task_service.list_tasks(session, skip=skip, limit=limit, status=status)


@router.post(
    "",
    response_model=SyncTaskResponse,
    summary="创建采集任务",
    description="data_type 必须在 catalog registry 中注册。",
)
async def create_task(
    body: SyncTaskCreate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> SyncTaskResponse:
    result = await _task_service.create_task(session, body)
    await session.commit()
    return result


@router.get(
    "/{task_id}",
    response_model=SyncTaskResponse,
    summary="任务详情",
)
async def get_task(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> SyncTaskResponse:
    return await _task_service.get_task(session, task_id)


@router.put(
    "/{task_id}",
    response_model=SyncTaskResponse,
    summary="更新任务",
)
async def update_task(
    task_id: int,
    body: SyncTaskUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> SyncTaskResponse:
    result = await _task_service.update_task(session, task_id, body)
    await session.commit()
    return result


@router.get(
    "/{task_id}/collect-config",
    response_model=CollectConfigResponse,
    summary="采集参数配置",
    description="返回默认探针参数、任务覆盖与合并后的有效参数；runtime_keys 由策略运行时注入不可编辑。",
)
async def get_task_collect_config(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> CollectConfigResponse:
    config = await _collect_config.get_for_task(session, task_id)
    return CollectConfigResponse(**config)


@router.get(
    "/{task_id}/runs",
    response_model=TaskRunPageResponse,
    summary="任务执行日志",
    description="分页查看 task_runs (D-08)。",
)
async def list_task_runs(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> TaskRunPageResponse:
    return await _run_service.list_runs(session, task_id, skip=skip, limit=limit)


@router.post(
    "/{task_id}/run",
    response_model=TaskRunTriggerResponse,
    summary="手动执行任务",
    description="创建 task_run 并触发 Celery。",
)
async def run_task(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> TaskRunTriggerResponse:
    return await _run_service.trigger(session, task_id)
