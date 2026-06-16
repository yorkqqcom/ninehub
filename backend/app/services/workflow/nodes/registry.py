"""Registered workflow node handlers."""

from __future__ import annotations

from app.core.exceptions import ValidationError
from app.services.workflow.nodes.base import NodeHandler
from app.services.workflow.nodes.collect import CollectNodeHandler
from app.services.workflow.nodes.gate import GateNodeHandler
from app.services.workflow.nodes.quality import QualityNodeHandler

NODE_HANDLERS: dict[str, NodeHandler] = {
    "gate": GateNodeHandler(),
    "collect": CollectNodeHandler(),
    "quality": QualityNodeHandler(),
}

ALLOWED_NODE_TYPES = frozenset(NODE_HANDLERS.keys())


def get_node_handler(node_type: str) -> NodeHandler:
    handler = NODE_HANDLERS.get(node_type)
    if handler is None:
        raise ValidationError(f"Unsupported node type: {node_type}")
    return handler
