"""Trading-day gate node."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.workflow import WorkflowNode
from app.services.trading_calendar.service import is_trading_day
from app.services.workflow.nodes.base import NodeExecutionContext, NodeResult


class GateNodeHandler:
    node_type = "gate"

    def execute(
        self,
        session: Session,
        node: WorkflowNode,
        *,
        skip_gates: bool = False,
        context: NodeExecutionContext | None = None,
    ) -> NodeResult:
        if skip_gates:
            return NodeResult(status="skipped", message="调试模式跳过 gate")
        ok, message = is_trading_day()
        if not ok:
            return NodeResult(status="failed", message=message)
        return NodeResult(status="success", message=message)
