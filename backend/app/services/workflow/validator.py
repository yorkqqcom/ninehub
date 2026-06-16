"""Workflow DAG validation (E-03 / E-04)."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from app.catalog.registry import get_data_type_entry
from app.core.exceptions import ValidationError
from app.models.workflow import WorkflowEdge, WorkflowNode
from app.services.tushare.quota import get_account_points
from app.services.workflow.dag import DagEngine
from app.services.workflow.nodes.registry import ALLOWED_NODE_TYPES


class WorkflowValidator:
    def __init__(self) -> None:
        self._dag = DagEngine()

    def validate_graph(
        self,
        nodes: Sequence[WorkflowNode],
        edges: Sequence[WorkflowEdge],
        *,
        for_publish: bool = False,
    ) -> None:
        errors = self.collect_errors(nodes, edges, for_publish=for_publish)
        if errors:
            raise ValidationError("DAG validation failed", details=errors)

    def collect_errors(
        self,
        nodes: Sequence[WorkflowNode],
        edges: Sequence[WorkflowEdge],
        *,
        for_publish: bool = False,
    ) -> list[str]:
        errors: list[str] = []
        if not nodes:
            errors.append("工作流至少需要一个节点")
            return errors

        node_ids = {n.node_id for n in nodes}
        for node in nodes:
            if node.node_type not in ALLOWED_NODE_TYPES:
                errors.append(f"节点 {node.node_id} 类型非法: {node.node_type}")
            if node.node_type in ("collect", "quality"):
                if not node.data_type:
                    errors.append(f"{node.node_type} 节点 {node.node_id} 缺少 data_type")
                elif get_data_type_entry(node.data_type) is None:
                    errors.append(
                        f"{node.node_type} 节点 {node.node_id} data_type 未注册: {node.data_type}"
                    )
            if node.node_type == "collect":
                if for_publish and node.source_id is None:
                    errors.append(f"collect 节点 {node.node_id} 缺少 source_id")
                if for_publish and node.data_type:
                    required = get_data_type_entry(node.data_type)
                    if required and required.min_points > get_account_points():
                        errors.append(
                            f"collect 节点 {node.node_id} 积分不足: "
                            f"需要 {required.min_points}，账户 {get_account_points()}"
                        )

        for edge in edges:
            if edge.source_node_id not in node_ids:
                errors.append(f"边源节点不存在: {edge.source_node_id}")
            if edge.target_node_id not in node_ids:
                errors.append(f"边目标节点不存在: {edge.target_node_id}")
            if edge.source_node_id == edge.target_node_id:
                errors.append(f"自环边: {edge.source_node_id}")

        if self._has_cycle(node_ids, edges):
            errors.append("DAG 存在环，禁止发布")

        if for_publish:
            connected = self._connected_nodes(node_ids, edges)
            orphans = node_ids - connected
            if orphans:
                errors.append(f"孤立节点（未连接）: {', '.join(sorted(orphans))}")

        return errors

    def topological_order(
        self,
        nodes: Sequence[WorkflowNode],
        edges: Sequence[WorkflowEdge],
    ) -> list[str]:
        self.validate_graph(nodes, edges)
        plan = self._dag.build_plan(list(nodes), list(edges))
        return self._dag.flat_order(plan)

    def execution_plan(
        self,
        nodes: Sequence[WorkflowNode],
        edges: Sequence[WorkflowEdge],
    ):
        self.validate_graph(nodes, edges)
        return self._dag.build_plan(list(nodes), list(edges))

    def _has_cycle(self, node_ids: set[str], edges: Sequence[WorkflowEdge]) -> bool:
        try:
            self._dag.build_plan(
                [WorkflowNode(workflow_id=0, node_id=nid, node_type="gate") for nid in node_ids],
                list(edges),
            )
            return False
        except ValueError:
            return True

    def _connected_nodes(self, node_ids: set[str], edges: Sequence[WorkflowEdge]) -> set[str]:
        if not edges:
            return set() if len(node_ids) > 1 else node_ids
        connected: set[str] = set()
        for edge in edges:
            connected.add(edge.source_node_id)
            connected.add(edge.target_node_id)
        return connected

    def _topological_sort_legacy(
        self,
        node_ids: set[str],
        edges: Sequence[WorkflowEdge],
    ) -> list[str] | None:
        indegree: dict[str, int] = {nid: 0 for nid in node_ids}
        adj: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids:
                adj[edge.source_node_id].append(edge.target_node_id)
                indegree[edge.target_node_id] += 1

        queue = [nid for nid, deg in indegree.items() if deg == 0]
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for nxt in adj[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        if len(order) != len(node_ids):
            return None
        return order
