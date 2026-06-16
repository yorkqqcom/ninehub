"""Task run schemas."""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class TaskRunResponse(BaseModel):
    id: int
    task_id: int
    status: str
    trigger_type: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    message: Optional[str] = None
    error: Optional[str] = None
    rows_upserted: int
    result_json: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskRunPageResponse(BaseModel):
    items: List[TaskRunResponse]
    total: int
    page: int
    size: int


class TaskRunTriggerResponse(BaseModel):
    run_id: int
    message: str
