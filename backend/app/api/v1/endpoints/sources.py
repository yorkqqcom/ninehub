"""Data source endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import RequireAdmin, get_current_user
from app.models.user import User
from app.schemas.datasource import (
    DataSourceCreate,
    DataSourcePageResponse,
    DataSourceResponse,
    DataSourceUpdate,
    DataSourceVerifyRequest,
    DataSourceVerifyResponse,
    TdxProbeRequest,
    TdxProbeResponse,
)
from app.services.datasource.service import DataSourceService

router = APIRouter()
_service = DataSourceService()


@router.get(
    "",
    response_model=DataSourcePageResponse,
    summary="数据源列表",
    description="列出已配置数据源；GET 响应中 token 须掩码。",
)
async def list_sources(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> DataSourcePageResponse:
    return await _service.list_sources(session, skip=skip, limit=limit)


@router.post(
    "",
    response_model=DataSourceResponse,
    summary="创建数据源",
    description="admin 创建 Tushare/AkShare 数据源；Tushare 须配置 account_points。",
)
async def create_source(
    body: DataSourceCreate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> DataSourceResponse:
    from fastapi import HTTPException

    from app.core.exceptions import ValidationError

    try:
        result = await _service.create_source(session, body)
        await session.commit()
        return result
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get(
    "/{source_id}",
    response_model=DataSourceResponse,
    summary="数据源详情",
)
async def get_source(
    source_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> DataSourceResponse:
    return await _service.get_source(session, source_id)


@router.put(
    "/{source_id}",
    response_model=DataSourceResponse,
    summary="更新数据源",
    description="PUT 空 token 保留原值。",
)
async def update_source(
    source_id: int,
    body: DataSourceUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> DataSourceResponse:
    result = await _service.update_source(session, source_id, body)
    await session.commit()
    return result


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除数据源",
)
async def delete_source(
    source_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> None:
    await _service.delete_source(session, source_id)
    await session.commit()


@router.post(
    "/verify",
    response_model=DataSourceVerifyResponse,
    summary="连通性校验",
    description="验证数据源 token 与网络连通性。",
)
async def verify_source(
    body: DataSourceVerifyRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> DataSourceVerifyResponse:
    return await _service.verify(session, body)


@router.post(
    "/tdx-probe",
    response_model=TdxProbeResponse,
    summary="TDX 路径探测",
    description="探测 Sidecar vipdoc 状态并可同步 install_root/paths 到 Sidecar。",
)
async def probe_tdx_source(
    body: TdxProbeRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> TdxProbeResponse:
    return await _service.probe_tdx(session, body)
