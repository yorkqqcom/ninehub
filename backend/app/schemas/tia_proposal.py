"""TIA proposal schemas."""

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.catalog import DataStandardIndexItem


class TiaProposalResponse(BaseModel):
    id: int
    api_name: str
    status: str
    action: str
    reason: Optional[str] = None
    job_id: Optional[int] = None
    data_type: Optional[str] = None
    reviewer_note: Optional[str] = None
    approved_by_id: Optional[int] = None
    activation_steps: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    doc_id: Optional[int] = None
    doc_url: Optional[str] = None
    min_points: Optional[int] = None
    min_points_doc: Optional[int] = Field(
        None, description="官网文档页解析积分（不含手动修正）"
    )
    min_points_override: Optional[int] = Field(
        None, description="人工修正积分；null 表示沿用文档/L1"
    )
    min_points_source: Optional[str] = Field(
        None, description="生效来源：manual | l1_override | doc_page"
    )
    label: Optional[str] = None
    category: Optional[str] = None
    browse_enabled: bool = False
    description: Optional[str] = Field(None, description="官网接口描述（wctapi）")
    input_params: List[dict[str, Any]] = Field(default_factory=list, description="入参")
    output_params: List[dict[str, Any]] = Field(default_factory=list, description="出参字段详情")
    output_fields: List[str] = Field(default_factory=list, description="出参字段名")
    sample_codes: List[str] = Field(default_factory=list, description="调用示例")
    sdk_valid: Optional[bool] = Field(None, description="SDK pro_api 校验")
    spec_source: Optional[str] = Field(None, description="规格来源：wctapi_md 等")

    model_config = {"from_attributes": True}


class TiaProposalMinPointsUpdate(BaseModel):
    min_points: Optional[int] = Field(
        None,
        ge=0,
        le=100000,
        description="人工修正积分；传 null 清除修正并恢复文档/L1 值",
    )


class TiaProposalReview(BaseModel):
    status: Literal["approved", "rejected"]
    note: Optional[str] = None
    domain: Optional[str] = Field(None, description="L1 业务域，审批通过时使用")
    run_preflight: bool = Field(False, description="批准时同步运行 Preflight 测试（10 项）")


class TiaPreflightCheckItem(BaseModel):
    key: str
    label: str
    status: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class TiaPreflightTestResponse(BaseModel):
    api_name: str
    passed: bool
    checks: List[TiaPreflightCheckItem]
    collect_pattern: dict[str, Any] = Field(default_factory=dict)
    blocking_errors: List[str] = Field(default_factory=list)


class TiaProposalSummary(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    applied: int = 0
    failed: int = 0
    total: int = 0


class TiaProposalPageResponse(BaseModel):
    items: List[TiaProposalResponse]
    total: int
    page: int
    size: int
    summary: Optional[TiaProposalSummary] = None


class TiaActivateResponse(BaseModel):
    job_id: int
    message: str


class TiaSchemaRepairResponse(BaseModel):
    api_name: str
    data_type: str
    table_name: str
    columns_before: List[str]
    columns_after: List[str]
    unique_keys_before: List[str]
    unique_keys_after: List[str]
    collect_mode: Optional[str] = None
    columns_added: List[str] = Field(default_factory=list)
    columns_dropped: List[str] = Field(default_factory=list)
    unique_index_created: bool = False
    browse_indexes_created: List[str] = Field(default_factory=list)
    indexes: List[DataStandardIndexItem] = Field(default_factory=list)
    unique_constraint: Optional[dict] = None
    sync_task_updated: bool = False
    schedule_cron: Optional[str] = None
    message: str = "Schema repaired"


class SchemaMappingChange(BaseModel):
    api_field: str
    before: Optional[str] = None
    after: Optional[str] = None


class SchemaRegistryHint(BaseModel):
    api_name: str
    registry_registered: bool
    heuristic_unique_keys: List[str] = Field(default_factory=list)
    registered_unique_keys: Optional[List[str]] = None
    suggested_unique_keys: List[str] = Field(default_factory=list)
    registry_snippet: str
    registry_file: str


class TiaSchemaPlanResponse(BaseModel):
    api_name: str
    data_type: str
    table_name: str
    columns_before: List[str]
    columns_after: List[str]
    columns_added: List[str] = Field(default_factory=list)
    columns_dropped: List[str] = Field(default_factory=list)
    mapping_changes: List[SchemaMappingChange] = Field(default_factory=list)
    collect_mode_before: Optional[str] = None
    collect_mode_after: Optional[str] = None
    unique_keys_before: List[str] = Field(default_factory=list)
    unique_keys_registry: List[str] = Field(default_factory=list)
    unique_keys_changed: bool = False
    columns_drift: bool = False
    keys_drift: bool = False
    registry_registered: bool = False
    registry_hint: SchemaRegistryHint
    row_count: int = 0
    ddl_errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    available_modes: List[str] = Field(default_factory=list)
    needs_confirm_risk: bool = False
    has_drift: bool = False


class TiaSchemaApplyRequest(BaseModel):
    modes: List[Literal["columns", "unique_keys"]] = Field(..., min_length=1)
    confirm_risk: bool = False


class TiaSchemaApplyResponse(TiaSchemaRepairResponse):
    modes_applied: List[str] = Field(default_factory=list)


class TiaBatchReview(BaseModel):
    proposal_ids: List[int] = Field(..., min_length=1, max_length=100)
    status: Literal["approved", "rejected"]
    note: Optional[str] = None
    domain: Optional[str] = None
    auto_activate: bool = Field(False, description="批准后自动排队 L3 激活")


class TiaBatchReviewResponse(BaseModel):
    items: List[TiaProposalResponse]
    activate_job_ids: List[int] = Field(default_factory=list)


class TiaBatchApproveActivate(BaseModel):
    proposal_ids: List[int] = Field(..., min_length=1, max_length=100)
    note: Optional[str] = None
    domain: Optional[str] = None
    skip_preflight: bool = Field(False, description="跳过 Preflight（不推荐）")


class TiaBatchApproveActivateItem(BaseModel):
    proposal_id: int
    success: bool
    job_id: Optional[int] = None
    error: Optional[str] = None


class TiaBatchApproveActivateResponse(BaseModel):
    items: List[TiaBatchApproveActivateItem]
    job_ids: List[int] = Field(default_factory=list)
    succeeded: int = 0
    failed: int = 0


class TiaBatchEnableBrowse(BaseModel):
    proposal_ids: List[int] = Field(..., min_length=1, max_length=100)


class TiaBatchActivate(BaseModel):
    proposal_ids: List[int] = Field(..., min_length=1, max_length=100)
    reapply: bool = Field(False, description="对已 applied/failed 提案补跑 L3（跳过已成功步骤）")


class TiaBatchActivateItem(BaseModel):
    proposal_id: int
    success: bool
    job_id: Optional[int] = None
    error: Optional[str] = None


class TiaBatchActivateResponse(BaseModel):
    items: List[TiaBatchActivateItem]
    job_ids: List[int] = Field(default_factory=list)
    succeeded: int = 0
    failed: int = 0


class TiaBatchEnableBrowseError(BaseModel):
    proposal_id: int
    error: str


class TiaBatchEnableBrowseResponse(BaseModel):
    items: List[TiaProposalResponse]
    succeeded: int = 0
    failed: int = 0
    errors: List[TiaBatchEnableBrowseError] = Field(default_factory=list)
