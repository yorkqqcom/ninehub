"""Workflow service — graph, history, publish, run, clone."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, ValidationError
from app.models.workflow import NodeRun, Workflow, WorkflowEdge, WorkflowNode, WorkflowRun
from app.schemas.workflow import (
    NodeRunListResponse,
    NodeRunResponse,
    WorkflowCloneResponse,
    WorkflowCollectProfileResponse,
    WorkflowCreate,
    WorkflowCreateResponse,
    WorkflowGraphResponse,
    WorkflowGraphUpdate,
    WorkflowListResponse,
    WorkflowMetaUpdate,
    WorkflowNodePatch,
    WorkflowNodeResponse,
    WorkflowEdgeResponse,
    WorkflowRunPageResponse,
    WorkflowRunResponse,
    WorkflowRunTriggerResponse,
    WorkflowSummaryResponse,
    WorkflowValidateResponse,
)
from app.services.platform.job_service import PlatformJobService
from app.services.tia.override_service import TiaOverrideService
from app.services.workflow.executor import WorkflowExecutor
from app.services.workflow.validator import WorkflowValidator


class WorkflowService:
    def __init__(self) -> None:
        self._validator = WorkflowValidator()
        self._executor = WorkflowExecutor()
        self._job_service = PlatformJobService()

    async def list_runs(
        self,
        session: AsyncSession,
        workflow_id: int,
        skip: int = 0,
        limit: int = 50,
    ) -> WorkflowRunPageResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        base = select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)
        count_query = (
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
        )
        total = (await session.execute(count_query)).scalar_one()
        result = await session.execute(
            base.order_by(WorkflowRun.id.desc()).offset(skip).limit(limit)
        )
        runs = result.scalars().all()
        page = (skip // limit) + 1 if limit else 1
        items = [
            WorkflowRunResponse(
                id=r.id,
                workflow_id=r.workflow_id,
                workflow_name=workflow.name,
                status=r.status,
                trigger_type=r.trigger_type,
                job_id=r.job_id,
                started_at=r.started_at,
                finished_at=r.finished_at,
                created_at=r.created_at,
            )
            for r in runs
        ]
        return WorkflowRunPageResponse(items=items, total=total, page=page, size=limit)

    async def get_run_nodes(
        self,
        session: AsyncSession,
        run_id: int,
    ) -> NodeRunListResponse:
        result = await session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .options(selectinload(WorkflowRun.node_runs))
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError(f"Workflow run {run_id} not found")
        nodes = sorted(run.node_runs, key=lambda n: n.id)
        items = [NodeRunResponse.model_validate(n) for n in nodes]
        return NodeRunListResponse(items=items, total=len(items))

    async def get_collect_profile(
        self,
        session: AsyncSession,
        *,
        data_type: str,
        batch_mode: str = "daily",
    ) -> WorkflowCollectProfileResponse:
        from app.catalog.registry import get_data_type_entry
        from app.core.exceptions import NotFoundError
        from app.services.tia.constants import resolve_canonical_data_type
        from app.services.tia.override_service import TiaOverrideService
        from app.services.workflow.collect_profile import build_workflow_collect_profile
        from app.sync.handlers import get_handler

        canonical = resolve_canonical_data_type(data_type)
        entry = get_data_type_entry(canonical) or get_data_type_entry(data_type)
        if entry is None:
            raise NotFoundError(f"data_type 未注册: {data_type}")

        response_data_type = entry.data_type
        api_name = canonical[len("tushare_") :] if canonical.startswith("tushare_") else canonical
        if canonical.startswith("tdx_"):
            api_name = canonical[len("tdx_") :]
        elif canonical.startswith("tia_"):
            api_name = canonical[len("tia_") :]
        elif response_data_type.startswith("tushare_"):
            api_name = response_data_type[len("tushare_") :]
        elif response_data_type.startswith("tdx_"):
            api_name = response_data_type[len("tdx_") :]
        elif response_data_type.startswith("tia_"):
            api_name = response_data_type[len("tia_") :]

        schema: dict = {}
        try:
            override = await TiaOverrideService().get_by_api(session, api_name)
            TiaOverrideService().bootstrap_override(override)
            payload = override.override_json or {}
            raw = payload.get("schema") or payload
            schema = dict(raw) if isinstance(raw, dict) else {}
        except NotFoundError:
            handler = get_handler(canonical)
            if handler is not None:
                schema = dict(getattr(handler, "schema") or {})

        profile = build_workflow_collect_profile(api_name, schema, batch_mode=batch_mode)
        return WorkflowCollectProfileResponse(data_type=response_data_type, **profile)

    async def get_run(
        self,
        session: AsyncSession,
        run_id: int,
    ) -> WorkflowRunResponse:
        result = await session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .options(selectinload(WorkflowRun.workflow))
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError(f"Workflow run {run_id} not found")
        return WorkflowRunResponse(
            id=run.id,
            workflow_id=run.workflow_id,
            workflow_name=run.workflow.name,
            status=run.status,
            trigger_type=run.trigger_type,
            job_id=run.job_id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            created_at=run.created_at,
        )

    async def create(
        self,
        session: AsyncSession,
        body: WorkflowCreate,
    ) -> WorkflowCreateResponse:
        existing = await session.execute(select(Workflow).where(Workflow.name == body.name))
        if existing.scalar_one_or_none() is not None:
            raise ValidationError(f"工作流名称已存在: {body.name}")
        workflow = Workflow(
            name=body.name,
            status="draft",
            description=body.description,
        )
        session.add(workflow)
        await session.flush()
        return WorkflowCreateResponse(
            workflow_id=workflow.id,
            name=workflow.name,
            message="工作流已创建",
        )

    async def delete(self, session: AsyncSession, workflow_id: int) -> str:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if workflow.status != "draft":
            raise ValidationError("仅 draft 工作流可删除")
        nodes, edges = await self._load_nodes_edges(session, workflow_id)
        for row in edges:
            await session.delete(row)
        for row in nodes:
            await session.delete(row)
        await session.delete(workflow)
        await session.flush()
        return f"工作流「{workflow.name}」已删除"

    async def unpublish(self, session: AsyncSession, workflow_id: int) -> str:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if workflow.status != "published":
            raise ValidationError("仅 published 工作流可取消发布")
        workflow.status = "draft"
        await session.flush()
        return f"工作流「{workflow.name}」已取消发布，恢复为 draft"

    async def validate(
        self,
        session: AsyncSession,
        workflow_id: int,
        *,
        for_publish: bool = False,
    ) -> WorkflowValidateResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        await TiaOverrideService().load_all_into_registry(session)
        nodes, edges = await self._load_nodes_edges(session, workflow_id)
        errors = self._validator.collect_errors(nodes, edges, for_publish=for_publish)
        warnings: list[str] = []
        if workflow.schedule_cron and workflow.status == "draft":
            warnings.append("draft 工作流不会被 Cron 调度")
        collect_nodes = [n for n in nodes if n.node_type == "collect" and not n.data_type]
        if collect_nodes and not for_publish:
            warnings.append(f"{len(collect_nodes)} 个 collect 节点未配置 data_type")
        return WorkflowValidateResponse(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    async def list_workflows(self, session: AsyncSession) -> WorkflowListResponse:
        result = await session.execute(select(Workflow).order_by(Workflow.id))
        workflows = result.scalars().all()
        items = []
        for w in workflows:
            node_count = (
                await session.execute(
                    select(func.count()).select_from(WorkflowNode).where(
                        WorkflowNode.workflow_id == w.id
                    )
                )
            ).scalar_one()
            items.append(
                WorkflowSummaryResponse(
                    id=w.id,
                    name=w.name,
                    status=w.status,
                    description=w.description,
                    schedule_cron=w.schedule_cron,
                    node_count=node_count,
                )
            )
        return WorkflowListResponse(items=items, total=len(items))

    async def get_graph(self, session: AsyncSession, workflow_id: int) -> WorkflowGraphResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        nodes_result = await session.execute(
            select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id)
        )
        edges_result = await session.execute(
            select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow_id)
        )
        return WorkflowGraphResponse(
            workflow_id=workflow.id,
            name=workflow.name,
            status=workflow.status,
            schedule_cron=workflow.schedule_cron,
            nodes=[WorkflowNodeResponse.model_validate(n) for n in nodes_result.scalars()],
            edges=[WorkflowEdgeResponse.model_validate(e) for e in edges_result.scalars()],
        )

    async def _load_nodes_edges(
        self,
        session: AsyncSession,
        workflow_id: int,
    ) -> tuple[list[WorkflowNode], list[WorkflowEdge]]:
        nodes = (
            await session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id))
        ).scalars().all()
        edges = (
            await session.execute(select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow_id))
        ).scalars().all()
        return list(nodes), list(edges)

    async def save_graph(
        self,
        session: AsyncSession,
        workflow_id: int,
        body: WorkflowGraphUpdate,
    ) -> WorkflowGraphResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if workflow.status != "draft":
            raise ValidationError("仅 draft 工作流可编辑图结构")

        draft_nodes = [
            WorkflowNode(
                workflow_id=workflow_id,
                node_id=n.node_id,
                node_type=n.node_type,
                label=n.label,
                position_x=n.position_x,
                position_y=n.position_y,
                data_type=n.data_type,
                source_id=n.source_id,
            )
            for n in body.nodes
        ]
        draft_edges = [
            WorkflowEdge(
                workflow_id=workflow_id,
                source_node_id=e.source_node_id,
                target_node_id=e.target_node_id,
            )
            for e in body.edges
        ]
        self._validator.validate_graph(draft_nodes, draft_edges)

        old_nodes = (
            await session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id))
        ).scalars().all()
        old_edges = (
            await session.execute(select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow_id))
        ).scalars().all()
        for row in old_nodes:
            await session.delete(row)
        for row in old_edges:
            await session.delete(row)
        await session.flush()

        for node in draft_nodes:
            session.add(node)
        for edge in draft_edges:
            session.add(edge)
        await session.flush()
        return await self.get_graph(session, workflow_id)

    async def update_node(
        self,
        session: AsyncSession,
        workflow_id: int,
        node_id: str,
        body: WorkflowNodePatch,
    ) -> WorkflowNodeResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if workflow.status != "draft":
            raise ValidationError("仅 draft 工作流可编辑节点属性")
        result = await session.execute(
            select(WorkflowNode).where(
                WorkflowNode.workflow_id == workflow_id,
                WorkflowNode.node_id == node_id,
            )
        )
        node = result.scalar_one_or_none()
        if node is None:
            raise NotFoundError(f"Node {node_id} not found")
        if body.label is not None:
            node.label = body.label
        if body.position_x is not None:
            node.position_x = body.position_x
        if body.position_y is not None:
            node.position_y = body.position_y
        if body.data_type is not None:
            node.data_type = body.data_type
        if body.source_id is not None:
            node.source_id = body.source_id
        await session.flush()
        return WorkflowNodeResponse.model_validate(node)

    async def update_meta(
        self,
        session: AsyncSession,
        workflow_id: int,
        body: WorkflowMetaUpdate,
    ) -> WorkflowSummaryResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if body.name is not None:
            if not body.name.strip():
                raise ValidationError("工作流名称不能为空")
            dup = await session.execute(
                select(Workflow).where(Workflow.name == body.name, Workflow.id != workflow_id)
            )
            if dup.scalar_one_or_none() is not None:
                raise ValidationError(f"工作流名称已存在: {body.name}")
            workflow.name = body.name.strip()
        if body.schedule_cron is not None:
            workflow.schedule_cron = body.schedule_cron or None
        if body.description is not None:
            workflow.description = body.description
        await session.flush()
        node_count = (
            await session.execute(
                select(func.count()).select_from(WorkflowNode).where(
                    WorkflowNode.workflow_id == workflow_id
                )
            )
        ).scalar_one()
        return WorkflowSummaryResponse(
            id=workflow.id,
            name=workflow.name,
            status=workflow.status,
            description=workflow.description,
            schedule_cron=workflow.schedule_cron,
            node_count=node_count,
        )

    async def publish(self, session: AsyncSession, workflow_id: int) -> str:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if workflow.status == "published":
            raise ValidationError("工作流已发布")
        nodes, edges = await self._load_nodes_edges(session, workflow_id)
        self._validator.validate_graph(nodes, edges, for_publish=True)
        workflow.status = "published"
        await session.flush()
        return f"工作流「{workflow.name}」已发布"

    async def clone(self, session: AsyncSession, workflow_id: int) -> WorkflowCloneResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        nodes, edges = await self._load_nodes_edges(session, workflow_id)

        clone_name = f"{workflow.name} (副本)"
        existing = await session.execute(select(Workflow).where(Workflow.name == clone_name))
        if existing.scalar_one_or_none() is not None:
            clone_name = f"{workflow.name} (副本 {workflow_id})"

        draft = Workflow(
            name=clone_name,
            status="draft",
            description=workflow.description,
        )
        session.add(draft)
        await session.flush()

        for node in nodes:
            session.add(
                WorkflowNode(
                    workflow_id=draft.id,
                    node_id=node.node_id,
                    node_type=node.node_type,
                    label=node.label,
                    position_x=node.position_x,
                    position_y=node.position_y,
                    data_type=node.data_type,
                    source_id=node.source_id,
                )
            )
        for edge in edges:
            session.add(
                WorkflowEdge(
                    workflow_id=draft.id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                )
            )
        await session.flush()
        return WorkflowCloneResponse(
            workflow_id=draft.id,
            name=draft.name,
            message="已克隆为 draft",
        )

    @staticmethod
    def _enqueue_workflow_run(run_id: int, *, skip_gates: bool = False) -> None:
        from app.tasks.dispatch import dispatch_task
        from app.tasks.workflow_tasks import run_workflow

        dispatch_task(run_workflow, run_id, skip_gates)

    async def trigger_run(
        self,
        session: AsyncSession,
        workflow_id: int,
        *,
        skip_gates: bool = False,
        trigger_type: str = "manual",
        async_queue: bool = True,
    ) -> WorkflowRunTriggerResponse:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        if skip_gates:
            trigger_type = "debug"
            async_queue = False
        elif workflow.status != "published":
            raise ValidationError("仅 published 工作流可正式运行；draft 请使用调试模式")

        nodes, edges = await self._load_nodes_edges(session, workflow_id)
        self._validator.validate_graph(nodes, edges)

        job = await self._job_service.create(session, "workflow_run")
        run = WorkflowRun(
            workflow_id=workflow_id,
            job_id=job.id,
            status="pending",
            trigger_type=trigger_type,
        )
        session.add(run)
        await session.flush()

        for node in nodes:
            session.add(
                NodeRun(
                    workflow_run_id=run.id,
                    node_id=node.node_id,
                    node_type=node.node_type,
                    label=node.label,
                    status="pending",
                )
            )
        await session.flush()

        if async_queue:
            await session.commit()
            self._enqueue_workflow_run(run.id, skip_gates=skip_gates)
            return WorkflowRunTriggerResponse(
                run_id=run.id,
                job_id=job.id,
                status="pending",
                message="工作流已加入队列",
            )

        await session.commit()
        await self._executor.execute_async(session, run.id, skip_gates=skip_gates)
        await session.refresh(run)
        return WorkflowRunTriggerResponse(
            run_id=run.id,
            job_id=job.id,
            status=run.status,
            message="工作流执行完成" if run.status == "success" else "工作流执行失败",
        )

    def trigger_run_sync(
        self,
        session,
        workflow_id: int,
        *,
        skip_gates: bool = False,
        trigger_type: str = "cron",
    ) -> WorkflowRunTriggerResponse:
        """Sync path for Celery Beat scheduler."""
        from sqlalchemy.orm import Session as OrmSession

        assert isinstance(session, OrmSession)
        workflow = session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if workflow.status != "published":
            raise ValidationError("仅 published 工作流可被调度")

        nodes = session.execute(
            select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id)
        ).scalars().all()
        edges = session.execute(
            select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow_id)
        ).scalars().all()
        self._validator.validate_graph(list(nodes), list(edges))

        job = self._job_service.create_sync(session, "workflow_run")
        run = WorkflowRun(
            workflow_id=workflow_id,
            job_id=job.id,
            status="pending",
            trigger_type=trigger_type,
        )
        session.add(run)
        session.flush()
        for node in nodes:
            session.add(
                NodeRun(
                    workflow_run_id=run.id,
                    node_id=node.node_id,
                    node_type=node.node_type,
                    label=node.label,
                    status="pending",
                )
            )
        session.flush()
        session.commit()
        self._enqueue_workflow_run(run.id, skip_gates=skip_gates)
        return WorkflowRunTriggerResponse(
            run_id=run.id,
            job_id=job.id,
            status="pending",
            message="工作流已加入队列",
        )
