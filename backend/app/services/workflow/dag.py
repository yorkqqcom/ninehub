"""DAG topology — layers, downstream skip on failure."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.models.workflow import WorkflowEdge, WorkflowNode


@dataclass
class DagPlan:
    """Execution plan: ordered layers + adjacency for skip propagation."""

    layers: list[list[str]]
    adj: dict[str, list[str]] = field(default_factory=dict)
    indegree: dict[str, int] = field(default_factory=dict)


class DagEngine:
    def build_plan(self, nodes: list[WorkflowNode], edges: list[WorkflowEdge]) -> DagPlan:
        node_ids = {n.node_id for n in nodes}
        indegree: dict[str, int] = {nid: 0 for nid in node_ids}
        adj: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids:
                adj[edge.source_node_id].append(edge.target_node_id)
                indegree[edge.target_node_id] += 1

        layers: list[list[str]] = []
        ready = [nid for nid, deg in indegree.items() if deg == 0]
        remaining = dict(indegree)

        while ready:
            layer = sorted(ready)
            layers.append(layer)
            next_ready: list[str] = []
            for nid in layer:
                for nxt in adj.get(nid, []):
                    remaining[nxt] -= 1
                    if remaining[nxt] == 0:
                        next_ready.append(nxt)
            ready = next_ready

        if sum(len(layer) for layer in layers) != len(node_ids):
            raise ValueError("DAG has cycle")

        return DagPlan(layers=layers, adj=dict(adj), indegree=indegree)

    def flat_order(self, plan: DagPlan) -> list[str]:
        order: list[str] = []
        for layer in plan.layers:
            order.extend(layer)
        return order

    def downstream_of(self, plan: DagPlan, node_id: str) -> set[str]:
        """All transitive descendants of node_id."""
        seen: set[str] = set()
        stack = list(plan.adj.get(node_id, []))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(plan.adj.get(current, []))
        return seen
