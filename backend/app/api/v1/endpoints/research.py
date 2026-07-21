"""Research / backtest API (ops console)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import RequireAdmin, get_current_user
from app.models.user import User
from app.schemas.research import (
    BacktestCreateRequest,
    BacktestEnqueueResponse,
    BacktestResultResponse,
    SignalDef,
)
from app.services.research.service import BacktestService

router = APIRouter()
_service = BacktestService()


@router.get(
    "/backtests/signals",
    response_model=list[SignalDef],
    summary="回测内置信号列表",
    description="供运营台表单渲染参数 schema。",
)
async def list_signals(
    _: Annotated[User, Depends(get_current_user)],
) -> list[SignalDef]:
    return [SignalDef.model_validate(x) for x in _service.list_signals()]


@router.post(
    "/backtests",
    response_model=BacktestEnqueueResponse,
    summary="提交回测任务",
    description="Admin 入队 platform_jobs(backtest_run)；立即返回 job_id。",
)
async def create_backtest(
    body: BacktestCreateRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: RequireAdmin,
) -> BacktestEnqueueResponse:
    job = await _service.enqueue(session, user, body.model_dump(mode="json"))
    return BacktestEnqueueResponse(job_id=job.id)


@router.get(
    "/backtests/{job_id}",
    response_model=BacktestResultResponse,
    summary="回测结果摘要",
    description="任务成功后返回 KPI、净值曲线与成交预览；进度请轮询 /platform/jobs/{id}。",
)
async def get_backtest(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> BacktestResultResponse:
    data = await _service.get_result(session, user, job_id)
    return BacktestResultResponse.model_validate(data)


@router.get(
    "/backtests/{job_id}/download",
    summary="下载回测完整 JSON",
    description="需登录；按 job 归属隔离。",
)
async def download_backtest(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    raw, filename = await _service.download_bytes(session, user, job_id)
    return Response(
        content=raw,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
