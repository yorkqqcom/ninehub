"""Seed 5 consolidated TIA workflows covering all 31 sync tasks (gate → collect DAG)."""

from __future__ import annotations

import asyncio
import sys
from typing import Iterable

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode

SOURCE_ID = 1

# (name, description, schedule_cron, [(node_id_suffix, label, data_type), ...])
WORKFLOW_SPECS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    (
        "01 盘前基础",
        "代码表与盘前参考：股票列表 → 北交所映射 → 融券标的 → 公司概况（08:00）",
        "0 8 * * 1-5",
        [
            ("stock_basic", "股票列表", "tushare_stock_basic"),
            ("bse_mapping", "北交所代码对照", "tushare_bse_mapping"),
            ("margin_secs", "融资融券标的", "tushare_margin_secs"),
            ("stock_company", "上市公司概况", "tushare_stock_company"),
        ],
    ),
    (
        "02 收盘行情",
        "收盘后行情链路：每日指标 → 复权因子 → 涨跌停 → 周线 → 两融汇总（18:00）",
        "0 18 * * 1-5",
        [
            ("daily_basic", "每日指标", "tushare_daily_basic"),
            ("adj_factor", "复权因子", "tushare_adj_factor"),
            ("stk_limit", "涨跌停价格", "tushare_stk_limit"),
            ("weekly", "周线行情", "tushare_weekly"),
            ("margin", "融资融券汇总", "tushare_margin"),
        ],
    ),
    (
        "03 财务披露",
        "基本面财报链：三大表 → 业绩快报/预告 → 财务指标 → 主营构成 → 披露日程（18:00）",
        "0 18 * * 1-5",
        [
            ("income", "利润表", "tushare_income"),
            ("balancesheet", "资产负债表", "tushare_balancesheet"),
            ("cashflow", "现金流量表", "tushare_cashflow"),
            ("express", "业绩快报", "tushare_express"),
            ("forecast", "业绩预告", "tushare_forecast"),
            ("fina_indicator", "财务指标", "tushare_fina_indicator"),
            ("fina_mainbz", "主营业务构成", "tushare_fina_mainbz"),
            ("disclosure_date", "财报披露日期", "tushare_disclosure_date"),
        ],
    ),
    (
        "04 股东治理",
        "股权与公司治理：前十大股东 → 流通股东 → 股东人数 → 管理层 → 薪酬 → 增减持 → 质押（18:00）",
        "0 18 * * 1-5",
        [
            ("top10_holders", "前十大股东", "tushare_top10_holders"),
            ("top10_floatholders", "前十大流通股东", "tushare_top10_floatholders"),
            ("stk_holdernumber", "股东人数", "tushare_stk_holdernumber"),
            ("stk_managers", "上市公司管理层", "tushare_stk_managers"),
            ("stk_rewards", "管理层薪酬持股", "tushare_stk_rewards"),
            ("stk_holdertrade", "股东增减持", "tushare_stk_holdertrade"),
            ("pledge_stat", "股权质押统计", "tushare_pledge_stat"),
            ("pledge_detail", "股权质押明细", "tushare_pledge_detail"),
        ],
    ),
    (
        "05 市场事件",
        "交易事件与资金：大宗 → 龙虎榜 → 分红 → 回购 → 沪深股通 → IPO（18:00）",
        "0 18 * * 1-5",
        [
            ("block_trade", "大宗交易", "tushare_block_trade"),
            ("top_list", "龙虎榜统计", "tushare_top_list"),
            ("dividend", "分红送股", "tushare_dividend"),
            ("repurchase", "股票回购", "tushare_repurchase"),
            ("hk_hold", "沪深股通持股", "tushare_hk_hold"),
            ("new_share", "IPO 新股上市", "tushare_new_share"),
        ],
    ),
]

_TIA_WORKFLOW_PREFIX = "0"


def _linear_graph(
    workflow_id: int,
    collects: Iterable[tuple[str, str, str]],
) -> tuple[list[WorkflowNode], list[WorkflowEdge]]:
    """gate → c1 → c2 → … linear DAG; wrap to second row when chain is long."""
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
    cols_per_row = 6
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
                position_x=80 + col * 200,
                position_y=120 + row * 140,
                data_type=data_type,
                source_id=SOURCE_ID,
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


async def _delete_tia_workflows(session) -> int:
    existing = (
        await session.execute(
            select(Workflow).where(Workflow.name.like(f"{_TIA_WORKFLOW_PREFIX}% %"))
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
        existing = (
            await session.execute(
                select(Workflow).where(Workflow.name.like(f"{_TIA_WORKFLOW_PREFIX}% %"))
            )
        ).scalars().all()
        if existing and not replace:
            print(f"Skip: {len(existing)} TIA workflow(s) already exist (use --replace).")
            for wf in existing:
                print(f"  - {wf.id}: {wf.name} ({wf.status})")
            return

        if replace and existing:
            removed = await _delete_tia_workflows(session)
            print(f"Removed {removed} existing TIA workflow(s).")

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
            nodes, edges = _linear_graph(wf.id, collects)
            session.add_all(nodes)
            session.add_all(edges)
            for _, _, dt in collects:
                covered.add(dt)
            created += 1
            print(
                f"Created workflow #{wf.id}: {name} "
                f"({len(collects)} collect nodes, cron={cron})"
            )

        await session.commit()
        print(f"\nDone: {created} workflows, {len(covered)} data_types covered.")
        if len(covered) != 31:
            print(f"WARNING: expected 31 data_types, got {len(covered)}")


def main() -> None:
    replace = "--replace" in sys.argv
    asyncio.run(seed(replace=replace))


if __name__ == "__main__":
    main()
