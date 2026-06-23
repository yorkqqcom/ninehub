"""Workflow execution engine — registry nodes + DAG skip propagation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.workflow import NodeRun, WorkflowEdge, WorkflowNode, WorkflowRun
from app.services.workflow.nodes.base import NodeExecutionContext
from app.services.workflow.collect_batch import resolve_run_batch_mode
from app.services.workflow.dag import DagEngine
from app.services.workflow.nodes.registry import get_node_handler
from app.services.workflow.validator import WorkflowValidator


class WorkflowExecutor:
    def __init__(self) -> None:
        self._validator = WorkflowValidator()
        self._dag = DagEngine()
        self._job_service = None

    def _jobs(self):
        if self._job_service is None:
            from app.services.platform.job_service import PlatformJobService

            self._job_service = PlatformJobService()
        return self._job_service

    async def execute_async(
        self,
        session: AsyncSession,
        run_id: int,
        *,
        skip_gates: bool = False,
    ) -> WorkflowRun:
        run = await self._load_run(session, run_id)
        nodes, edges = await self._load_graph(session, run.workflow_id)
        plan = self._validator.execution_plan(nodes, edges)
        node_map = {n.node_id: n for n in nodes}
        order = self._dag.flat_order(plan)

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await session.flush()
        if run.job_id:
            await self._jobs().update(
                session,
                run.job_id,
                status="running",
                progress=5,
                message="工作流开始执行",
            )
            await session.commit()

        skipped: set[str] = set()
        try:
            total = len(order)
            for idx, node_id in enumerate(order):
                if node_id in skipped:
                    node_run = await self._get_node_run(session, run.id, node_id)
                    await self._finish_node(
                        session,
                        node_run,
                        status="skipped",
                        message="上游节点失败，已跳过",
                    )
                    await session.commit()
                    continue

                node = node_map[node_id]
                node_run = await self._get_node_run(session, run.id, node_id)
                result = await self._execute_node(session, node_run, node, skip_gates=skip_gates)

                if result == "failed":
                    skipped.update(self._dag.downstream_of(plan, node_id))
                    run.status = "failed"
                    await session.commit()
                    break

                if run.job_id:
                    pct = 10 + int(80 * (idx + 1) / max(total, 1))
                    await self._jobs().update(
                        session,
                        run.job_id,
                        progress=pct,
                        message=f"节点 {node.label or node_id} 完成",
                    )
                    await session.commit()
            else:
                run.status = "success"
        except Exception as exc:
            await session.rollback()
            run = await self._load_run(session, run_id)
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            if run.job_id:
                await self._jobs().update(
                    session,
                    run.job_id,
                    status="failed",
                    progress=0,
                    message="工作流执行失败",
                    error=str(exc),
                )
            await session.commit()
            raise ValidationError(str(exc)) from exc

        run.finished_at = datetime.now(timezone.utc)
        if run.job_id:
            await self._jobs().update(
                session,
                run.job_id,
                status="success" if run.status == "success" else "failed",
                progress=100 if run.status == "success" else 0,
                message="工作流执行完成" if run.status == "success" else "工作流执行失败",
                result_json={"run_id": run.id, "workflow_id": run.workflow_id},
            )
        await session.commit()
        return run

    def execute_sync(
        self,
        session: Session,
        run_id: int,
        *,
        skip_gates: bool = False,
    ) -> WorkflowRun:
        run = session.get(WorkflowRun, run_id)
        if run is None:
            raise NotFoundError(f"Workflow run {run_id} not found")

        nodes = session.execute(
            select(WorkflowNode).where(WorkflowNode.workflow_id == run.workflow_id)
        ).scalars().all()
        edges = session.execute(
            select(WorkflowEdge).where(WorkflowEdge.workflow_id == run.workflow_id)
        ).scalars().all()
        plan = self._validator.execution_plan(nodes, edges)
        node_map = {n.node_id: n for n in nodes}
        order = self._dag.flat_order(plan)

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        session.flush()
        if run.job_id:
            self._jobs().update_sync(
                session,
                run.job_id,
                status="running",
                progress=5,
                message="工作流开始执行",
            )

        skipped: set[str] = set()
        try:
            total = len(order)
            for idx, node_id in enumerate(order):
                if node_id in skipped:
                    node_run = session.execute(
                        select(NodeRun).where(
                            NodeRun.workflow_run_id == run.id,
                            NodeRun.node_id == node_id,
                        )
                    ).scalar_one()
                    self._finish_node_sync(
                        session,
                        node_run,
                        status="skipped",
                        message="上游节点失败，已跳过",
                    )
                    continue

                node = node_map[node_id]
                node_run = session.execute(
                    select(NodeRun).where(
                        NodeRun.workflow_run_id == run.id,
                        NodeRun.node_id == node_id,
                    )
                ).scalar_one()
                result = self._execute_node_sync(session, node_run, node, skip_gates=skip_gates)

                if result == "failed":
                    skipped.update(self._dag.downstream_of(plan, node_id))
                    run.status = "failed"
                    break

                if run.job_id:
                    pct = 10 + int(80 * (idx + 1) / max(total, 1))
                    self._jobs().update_sync(
                        session,
                        run.job_id,
                        progress=pct,
                        message=f"节点 {node.label or node_id} 完成",
                    )
            else:
                run.status = "success"
        except Exception as exc:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            if run.job_id:
                self._jobs().update_sync(
                    session,
                    run.job_id,
                    status="failed",
                    progress=0,
                    message="工作流执行失败",
                    error=str(exc),
                )
            session.flush()
            raise ValidationError(str(exc)) from exc

        run.finished_at = datetime.now(timezone.utc)
        if run.job_id:
            self._jobs().update_sync(
                session,
                run.job_id,
                status="success" if run.status == "success" else "failed",
                progress=100 if run.status == "success" else 0,
                message="工作流执行完成" if run.status == "success" else "工作流执行失败",
                result_json={"run_id": run.id, "workflow_id": run.workflow_id},
            )
        session.flush()
        return run

    async def _load_run(self, session: AsyncSession, run_id: int) -> WorkflowRun:
        result = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError(f"Workflow run {run_id} not found")
        return run

    async def _load_graph(
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

    async def _get_node_run(
        self,
        session: AsyncSession,
        run_id: int,
        node_id: str,
    ) -> NodeRun:
        result = await session.execute(
            select(NodeRun).where(NodeRun.workflow_run_id == run_id, NodeRun.node_id == node_id)
        )
        node_run = result.scalar_one_or_none()
        if node_run is None:
            raise NotFoundError(f"NodeRun {node_id} not found for run {run_id}")
        return node_run

    async def _execute_node(
        self,
        session: AsyncSession,
        node_run: NodeRun,
        node: WorkflowNode,
        *,
        skip_gates: bool,
    ) -> str:
        """Returns terminal status: success | failed | skipped."""
        node_run.status = "running"
        node_run.started_at = datetime.now(timezone.utc)
        await session.flush()
        handler = get_node_handler(node.node_type)
        run_id = node_run.workflow_run_id
        node_id = node.node_id
        run = await self._load_run(session, run_id)
        ctx = NodeExecutionContext(
            workflow_id=run.workflow_id,
            workflow_run_id=run_id,
            node_id=node_id,
            trigger_type=run.trigger_type,
            batch_mode=resolve_run_batch_mode(run.trigger_type),
        )
        try:

            def _run(sync_sess: Session) -> object:
                return handler.execute(sync_sess, node, skip_gates=skip_gates, context=ctx)

            result = await session.run_sync(_run)
            await self._finish_node(
                session,
                node_run,
                status=result.status,
                message=result.message,
                detail_json=result.detail_json,
            )
            await session.commit()
            return "failed" if result.status == "failed" else "success"
        except Exception as exc:
            await session.rollback()
            node_run = await self._get_node_run(session, run_id, node_id)
            await self._finish_node(session, node_run, status="failed", message=str(exc)[:2000])
            await session.commit()
            return "failed"

    def _execute_node_sync(
        self,
        session: Session,
        node_run: NodeRun,
        node: WorkflowNode,
        *,
        skip_gates: bool,
    ) -> str:
        node_run.status = "running"
        node_run.started_at = datetime.now(timezone.utc)
        session.flush()
        handler = get_node_handler(node.node_type)
        run = session.get(WorkflowRun, node_run.workflow_run_id)
        if run is None:
            raise NotFoundError(f"Workflow run {node_run.workflow_run_id} not found")
        ctx = NodeExecutionContext(
            workflow_id=run.workflow_id,
            workflow_run_id=run.id,
            node_id=node.node_id,
            trigger_type=run.trigger_type,
            batch_mode=resolve_run_batch_mode(run.trigger_type),
        )
        try:
            result = handler.execute(session, node, skip_gates=skip_gates, context=ctx)
            self._finish_node_sync(
                session,
                node_run,
                status=result.status,
                message=result.message,
                detail_json=result.detail_json,
            )
            return "failed" if result.status == "failed" else "success"
        except Exception as exc:
            self._finish_node_sync(session, node_run, status="failed", message=str(exc)[:2000])
            return "failed"

    async def _finish_node(
        self,
        session: AsyncSession,
        node_run: NodeRun,
        *,
        status: str,
        message: str,
        detail_json: dict | None = None,
    ) -> None:
        node_run.status = status
        node_run.message = message
        node_run.result_json = detail_json
        node_run.finished_at = datetime.now(timezone.utc)
        await session.flush()

    def _finish_node_sync(
        self,
        session: Session,
        node_run: NodeRun,
        *,
        status: str,
        message: str,
        detail_json: dict | None = None,
    ) -> None:
        node_run.status = status
        node_run.message = message
        node_run.result_json = detail_json
        node_run.finished_at = datetime.now(timezone.utc)
        session.flush()
