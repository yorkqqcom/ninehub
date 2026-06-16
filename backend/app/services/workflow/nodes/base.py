"""Workflow node handler protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.workflow import WorkflowNode


@dataclass
class NodeResult:
    status: str  # success | failed | skipped
    message: str = ""
    detail_json: dict | None = None


@dataclass(frozen=True)
class NodeExecutionContext:
    workflow_id: int
    workflow_run_id: int
    node_id: str
    trigger_type: str = "manual"
    batch_mode: str | None = None


class NodeHandler(Protocol):
    node_type: str

    def execute(
        self,
        session: Session,
        node: WorkflowNode,
        *,
        skip_gates: bool = False,
        context: NodeExecutionContext | None = None,
    ) -> NodeResult:
        """Run node logic synchronously (Celery / inline executor path)."""
