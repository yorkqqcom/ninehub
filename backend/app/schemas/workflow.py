"""Workflow schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class WorkflowRunResponse(BaseModel):
    id: int
    workflow_id: int
    workflow_name: str
    status: str
    trigger_type: str
    job_id: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunPageResponse(BaseModel):
    items: List[WorkflowRunResponse]
    total: int
    page: int
    size: int


class WorkflowSummaryResponse(BaseModel):
    id: int
    name: str
    status: str
    description: Optional[str] = None
    schedule_cron: Optional[str] = None
    node_count: int = 0

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    items: List[WorkflowSummaryResponse]
    total: int


class WorkflowNodeResponse(BaseModel):
    id: int
    workflow_id: int
    node_id: str
    node_type: str
    label: Optional[str] = None
    position_x: float
    position_y: float
    data_type: Optional[str] = None
    source_id: Optional[int] = None

    model_config = {"from_attributes": True}


class WorkflowEdgeResponse(BaseModel):
    id: int
    workflow_id: int
    source_node_id: str
    target_node_id: str

    model_config = {"from_attributes": True}


class WorkflowGraphResponse(BaseModel):
    workflow_id: int
    name: str
    status: str
    schedule_cron: Optional[str] = None
    nodes: List[WorkflowNodeResponse]
    edges: List[WorkflowEdgeResponse]


class WorkflowNodeInput(BaseModel):
    node_id: str
    node_type: str
    label: Optional[str] = None
    position_x: float = 0
    position_y: float = 0
    data_type: Optional[str] = None
    source_id: Optional[int] = None


class WorkflowEdgeInput(BaseModel):
    source_node_id: str
    target_node_id: str


class WorkflowGraphUpdate(BaseModel):
    nodes: List[WorkflowNodeInput]
    edges: List[WorkflowEdgeInput]


class WorkflowNodePatch(BaseModel):
    label: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    data_type: Optional[str] = None
    source_id: Optional[int] = None


class WorkflowMetaUpdate(BaseModel):
    name: Optional[str] = None
    schedule_cron: Optional[str] = None
    description: Optional[str] = None


class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None


class WorkflowCreateResponse(BaseModel):
    workflow_id: int
    name: str
    message: str


class WorkflowValidateResponse(BaseModel):
    valid: bool
    errors: List[str]
    warnings: List[str] = []


class NodeRunResponse(BaseModel):
    id: int
    workflow_run_id: int
    node_id: str
    node_type: str
    label: Optional[str] = None
    status: str
    message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class NodeRunListResponse(BaseModel):
    items: List[NodeRunResponse]
    total: int


class WorkflowRunTriggerResponse(BaseModel):
    run_id: int
    job_id: Optional[int] = None
    status: str
    message: str


class WorkflowCloneResponse(BaseModel):
    workflow_id: int
    name: str
    message: str
