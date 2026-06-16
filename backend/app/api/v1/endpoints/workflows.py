"""Workflow endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import RequireAdmin, get_current_user
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.workflow import (
    NodeRunListResponse,
    WorkflowCloneResponse,
    WorkflowCreate,
    WorkflowCreateResponse,
    WorkflowGraphResponse,
    WorkflowGraphUpdate,
    WorkflowListResponse,
    WorkflowMetaUpdate,
    WorkflowNodePatch,
    WorkflowNodeResponse,
    WorkflowRunPageResponse,
    WorkflowRunResponse,
    WorkflowRunTriggerResponse,
    WorkflowSummaryResponse,
    WorkflowValidateResponse,
)
from app.services.workflow.service import WorkflowService

router = APIRouter()
_workflow_service = WorkflowService()


@router.get(
    "",
    response_model=WorkflowListResponse,
    summary="工作流列表",
)
async def list_workflows(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> WorkflowListResponse:
    return await _workflow_service.list_workflows(session)


@router.post(
    "",
    response_model=WorkflowCreateResponse,
    summary="创建工作流",
    description="创建空白 draft 工作流，可在画布中添加节点。",
)
async def create_workflow(
    body: WorkflowCreate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> WorkflowCreateResponse:
    result = await _workflow_service.create(session, body)
    await session.commit()
    return result


@router.get(
    "/{workflow_id}/graph",
    response_model=WorkflowGraphResponse,
    summary="工作流图结构",
    description="节点与边，供 Vue Flow 渲染。",
)
async def get_workflow_graph(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> WorkflowGraphResponse:
    return await _workflow_service.get_graph(session, workflow_id)


@router.get(
    "/{workflow_id}/validate",
    response_model=WorkflowValidateResponse,
    summary="校验工作流 DAG",
    description="返回校验错误与警告，发布前可预览。",
)
async def validate_workflow(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    for_publish: bool = Query(False, description="按发布标准校验"),
) -> WorkflowValidateResponse:
    return await _workflow_service.validate(session, workflow_id, for_publish=for_publish)


@router.get(
    "/runs/{run_id}",
    response_model=WorkflowRunResponse,
    summary="工作流运行详情",
    description="单次 workflow_run 摘要信息。",
)
async def get_workflow_run(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> WorkflowRunResponse:
    return await _workflow_service.get_run(session, run_id)


@router.get(
    "/runs/{run_id}/nodes",
    response_model=NodeRunListResponse,
    summary="节点运行详情",
    description="查看某次运行的全部 node_runs 状态(E-09)。",
)
async def get_workflow_run_nodes(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> NodeRunListResponse:
    return await _workflow_service.get_run_nodes(session, run_id)


@router.get(
    "/{workflow_id}/runs",
    response_model=WorkflowRunPageResponse,
    summary="工作流运行历史",
    description="分页查看 workflow_runs(E-09)。",
)
async def list_workflow_runs(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> WorkflowRunPageResponse:
    return await _workflow_service.list_runs(session, workflow_id, skip=skip, limit=limit)


@router.post(
    "/{workflow_id}/publish",
    response_model=MessageResponse,
    summary="发布工作流",
    description="draft → published，发布前 DAG 校验(E-03)。",
)
async def publish_workflow(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> MessageResponse:
    message = await _workflow_service.publish(session, workflow_id)
    await session.commit()
    return MessageResponse(message=message)


@router.post(
    "/{workflow_id}/unpublish",
    response_model=MessageResponse,
    summary="取消发布",
    description="published → draft，停止 Cron 调度。",
)
async def unpublish_workflow(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> MessageResponse:
    message = await _workflow_service.unpublish(session, workflow_id)
    await session.commit()
    return MessageResponse(message=message)


@router.post(
    "/{workflow_id}/clone",
    response_model=WorkflowCloneResponse,
    summary="克隆工作流模板",
    description="复制为 draft 副本(E-10)。",
)
async def clone_workflow(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> WorkflowCloneResponse:
    result = await _workflow_service.clone(session, workflow_id)
    await session.commit()
    return result


@router.delete(
    "/{workflow_id}",
    response_model=MessageResponse,
    summary="删除工作流",
    description="仅 draft 可删除。",
)
async def delete_workflow(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> MessageResponse:
    message = await _workflow_service.delete(session, workflow_id)
    await session.commit()
    return MessageResponse(message=message)


@router.post(
    "/{workflow_id}/run",
    response_model=WorkflowRunTriggerResponse,
    summary="运行工作流",
    description="手动触发 published 工作流；admin 可 skip_gates 调试 draft(E-07)。",
)
async def run_workflow(
    workflow_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
    skip_gates: bool = Query(False, description="跳过 gate 节点，仅 admin 调试"),
    async_queue: bool = Query(
        True,
        description="加入 Celery 队列异步执行（默认）；false 时同步等待完成",
    ),
    batch_mode: str = Query(
        "daily",
        description="采集批次：daily=每日增量（默认）；backfill=从 sync_start_date 全量回填",
    ),
) -> WorkflowRunTriggerResponse:
    trigger_type = "debug" if skip_gates else ("backfill" if batch_mode == "backfill" else "manual")
    result = await _workflow_service.trigger_run(
        session,
        workflow_id,
        skip_gates=skip_gates,
        trigger_type=trigger_type,
        async_queue=async_queue,
    )
    await session.commit()
    return result


@router.put(
    "/{workflow_id}/graph",
    response_model=WorkflowGraphResponse,
    summary="保存工作流图",
    description="draft 工作流批量保存节点与边(E-11)。",
)
async def save_workflow_graph(
    workflow_id: int,
    body: WorkflowGraphUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> WorkflowGraphResponse:
    result = await _workflow_service.save_graph(session, workflow_id, body)
    await session.commit()
    return result


@router.patch(
    "/{workflow_id}/nodes/{node_id}",
    response_model=WorkflowNodeResponse,
    summary="更新节点属性",
    description="编辑 collect/quality 节点 source/data_type 等(E-11)。",
)
async def patch_workflow_node(
    workflow_id: int,
    node_id: str,
    body: WorkflowNodePatch,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> WorkflowNodeResponse:
    result = await _workflow_service.update_node(session, workflow_id, node_id, body)
    await session.commit()
    return result


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowSummaryResponse,
    summary="更新工作流元数据",
    description="名称、Cron 调度表达式、描述等(E-06)。",
)
async def patch_workflow_meta(
    workflow_id: int,
    body: WorkflowMetaUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> WorkflowSummaryResponse:
    result = await _workflow_service.update_meta(session, workflow_id, body)
    await session.commit()
    return result
