"""Seed demo workflow template (catalog types via TIA L3)."""

import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        wf_result = await session.execute(
            select(Workflow).where(Workflow.name == "交易日收盘同步")
        )
        workflow = wf_result.scalar_one_or_none()
        if workflow is None:
            workflow = Workflow(
                name="交易日收盘同步",
                status="published",
                description="预设模板：交易日 gate → 采集节点（data_type 在发布后配置）",
                schedule_cron="0 18 * * 1-5",
            )
            session.add(workflow)
            await session.flush()
            session.add_all(
                [
                    WorkflowNode(
                        workflow_id=workflow.id,
                        node_id="gate-1",
                        node_type="gate",
                        label="交易日",
                        position_x=80,
                        position_y=120,
                    ),
                    WorkflowNode(
                        workflow_id=workflow.id,
                        node_id="collect-1",
                        node_type="collect",
                        label="采集",
                        position_x=280,
                        position_y=120,
                        data_type=None,
                        source_id=1,
                    ),
                ]
            )
            session.add(
                WorkflowEdge(
                    workflow_id=workflow.id,
                    source_node_id="gate-1",
                    target_node_id="collect-1",
                )
            )

        await session.commit()
        print("Demo seed completed.")


if __name__ == "__main__":
    asyncio.run(seed())
