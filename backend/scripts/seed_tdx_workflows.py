"""Seed published TDX collect workflows (gate → collect DAG)."""

from __future__ import annotations

import asyncio
import sys
from typing import Iterable

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.data_source import DataSource
from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode

_TDX_WORKFLOW_PREFIX = "TDX"

# (name, description, schedule_cron, [(node_suffix, label, data_type), ...])
WORKFLOW_SPECS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    (
        "TDX 01 T+1 行情",
        "通达信 vipdoc 导入（file_first 网络补洞）：日线 → 1分钟 → 5分钟（工作日 07:00）",
        "0 7 * * 1-5",
        [
            ("bar_1d", "通达信日线", "tdx_bar_1d"),
            ("bar_1m", "通达信1分钟", "tdx_bar_1m"),
            ("bar_5m", "通达信5分钟", "tdx_bar_5m"),
        ],
    ),
    (
        "TDX 02 概念快照",
        "通达信概念板块与成分股日快照（工作日 07:15，依赖 bar/代码表）",
        "15 7 * * 1-5",
        [
            ("concept_index", "概念板块", "tdx_concept_index"),
            ("concept_member", "概念成分", "tdx_concept_member"),
        ],
    ),
]


async def _resolve_tdx_source_id(session) -> int:
    row = (
        await session.execute(
            select(DataSource.id)
            .where(DataSource.provider == "tdx", DataSource.status == "active")
            .order_by(DataSource.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise RuntimeError("无 active TDX 数据源，请先在「数据源」页配置 Sidecar base_url")
    return int(row)


def _linear_graph(
    workflow_id: int,
    source_id: int,
    collects: Iterable[tuple[str, str, str]],
) -> tuple[list[WorkflowNode], list[WorkflowEdge]]:
    nodes: list[WorkflowNode] = [
        WorkflowNode(
            workflow_id=workflow_id,
            node_id="gate-1",
            node_type="gate",
            label="交易日",
            position_x=80,
            position_y=160,
        )
    ]
    edges: list[WorkflowEdge] = []
    prev = "gate-1"
    cols_per_row = 4
    for idx, (suffix, label, data_type) in enumerate(collects, start=1):
        node_id = f"collect-{suffix}"
        col = (idx - 1) % cols_per_row
        row = (idx - 1) // cols_per_row
        nodes.append(
            WorkflowNode(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type="collect",
                label=label,
                position_x=80 + col * 220,
                position_y=120 + row * 140,
                data_type=data_type,
                source_id=source_id,
            )
        )
        edges.append(
            WorkflowEdge(
                workflow_id=workflow_id,
                source_node_id=prev,
                target_node_id=node_id,
            )
        )
        prev = node_id
    return nodes, edges


async def _delete_tdx_workflows(session) -> int:
    existing = (
        await session.execute(
            select(Workflow).where(Workflow.name.like(f"{_TDX_WORKFLOW_PREFIX}%"))
        )
    ).scalars().all()
    for wf in existing:
        for edge in (
            await session.execute(
                select(WorkflowEdge).where(WorkflowEdge.workflow_id == wf.id)
            )
        ).scalars():
            await session.delete(edge)
        for node in (
            await session.execute(
                select(WorkflowNode).where(WorkflowNode.workflow_id == wf.id)
            )
        ).scalars():
            await session.delete(node)
        await session.delete(wf)
    return len(existing)


async def seed(*, replace: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        source_id = await _resolve_tdx_source_id(session)
        print(f"TDX source_id={source_id}")

        existing = (
            await session.execute(
                select(Workflow).where(Workflow.name.like(f"{_TDX_WORKFLOW_PREFIX}%"))
            )
        ).scalars().all()
        if existing and not replace:
            print(f"Skip: {len(existing)} TDX workflow(s) exist (use --replace).")
            for wf in existing:
                print(f"  - {wf.id}: {wf.name} ({wf.status})")
            return

        if replace and existing:
            removed = await _delete_tdx_workflows(session)
            print(f"Removed {removed} existing TDX workflow(s).")

        created = 0
        covered: set[str] = set()
        for name, description, cron, collects in WORKFLOW_SPECS:
            wf = Workflow(
                name=name,
                status="published",
                description=description,
                schedule_cron=cron,
            )
            session.add(wf)
            await session.flush()
            nodes, edges = _linear_graph(wf.id, source_id, collects)
            session.add_all(nodes)
            session.add_all(edges)
            for _, _, dt in collects:
                covered.add(dt)
            created += 1
            print(
                f"Created workflow #{wf.id}: {name} "
                f"({len(collects)} nodes, cron={cron}, source_id={source_id})"
            )

        await session.commit()
        print(f"\nDone: {created} TDX workflows, {len(covered)} data_types.")


def main() -> None:
    replace = "--replace" in sys.argv
    asyncio.run(seed(replace=replace))


if __name__ == "__main__":
    main()
