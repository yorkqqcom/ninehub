"""Quality check node — runs enabled rules for a data_type."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SyncSessionLocal
from app.core.exceptions import ValidationError
from app.models.workflow import WorkflowNode
from app.services.quality.service import QualityService
from app.services.workflow.nodes.base import NodeExecutionContext, NodeResult


class QualityNodeHandler:
    node_type = "quality"

    def execute(
        self,
        session: Session,
        node: WorkflowNode,
        *,
        skip_gates: bool = False,
        context: NodeExecutionContext | None = None,
    ) -> NodeResult:
        if not node.data_type:
            raise ValidationError(f"quality 节点 {node.node_id} 缺少 data_type")
        quality_session = SyncSessionLocal()
        try:
            result = QualityService().run_check_sync(quality_session, data_type=node.data_type)
            quality_session.commit()
        except Exception:
            quality_session.rollback()
            raise
        finally:
            quality_session.close()
        status = "failed" if result.alerts_sent else "success"
        return NodeResult(status=status, message=result.message)
