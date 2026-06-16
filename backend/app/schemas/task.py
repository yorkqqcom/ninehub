"""Sync task schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SyncTaskCreate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    source_id: Optional[int] = None
    data_type: str = Field(min_length=1, max_length=64)
    schedule_cron: Optional[str] = Field(None, max_length=64)
    status: str = Field(default="active", pattern="^(active|paused)$")
    upstream_task_id: Optional[int] = None
    collect_params: Optional[Dict[str, Any]] = Field(
        None,
        description="任务级 Tushare 采集参数覆盖（不含 fields/limit 探针键）",
    )


class SyncTaskUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    source_id: Optional[int] = None
    data_type: Optional[str] = Field(None, min_length=1, max_length=64)
    schedule_cron: Optional[str] = Field(None, max_length=64)
    status: Optional[str] = Field(None, pattern="^(active|paused)$")
    upstream_task_id: Optional[int] = None
    collect_params: Optional[Dict[str, Any]] = Field(
        None,
        description="设为 {} 清空覆盖；省略则不修改",
    )


class SyncTaskResponse(BaseModel):
    id: int
    name: Optional[str] = None
    source_id: Optional[int] = None
    data_type: str
    data_type_label: str
    schedule_cron: Optional[str] = None
    status: str
    upstream_task_id: Optional[int] = None
    next_run_at: Optional[datetime] = None
    tia_api_name: Optional[str] = None
    proposal_id: Optional[int] = None
    source_name: Optional[str] = None
    collect_params: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CollectConfigResponse(BaseModel):
    task_id: int
    data_type: str
    api_name: Optional[str] = None
    collect_mode: Optional[str] = None
    collect_pattern: Optional[str] = None
    default_params: Dict[str, Any] = Field(default_factory=dict)
    task_overrides: Dict[str, Any] = Field(default_factory=dict)
    effective_params: Dict[str, Any] = Field(default_factory=dict)
    runtime_keys: List[str] = Field(default_factory=list)
    editable_keys: List[str] = Field(default_factory=list)
    param_hints: Dict[str, str] = Field(default_factory=dict)


class SyncTaskPageResponse(BaseModel):
    items: List[SyncTaskResponse]
    total: int
    page: int
    size: int
