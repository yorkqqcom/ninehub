"""Pydantic schemas for Data Browser query engine."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class UniversePreset(BaseModel):
    type: Literal["preset"] = "preset"
    preset: str = Field(..., description="all_ab | all_a | all_b | index:xxx | custom")


class UniverseCustom(BaseModel):
    type: Literal["custom"] = "custom"
    codes: list[str] = Field(default_factory=list)


class UniverseWatchlist(BaseModel):
    type: Literal["watchlist"] = "watchlist"
    watchlist_id: int


UniverseSpec = UniversePreset | UniverseCustom | UniverseWatchlist


class IndicatorSelection(BaseModel):
    id: str
    adjust: Optional[Literal["none", "hfq", "qfq"]] = None


class BrowserSort(BaseModel):
    column: str
    direction: Literal["asc", "desc"] = "desc"


class BrowserExecuteRequest(BaseModel):
    universe: UniverseSpec
    as_of_date: date
    dates: Optional[list[date]] = Field(None, max_length=5)
    indicators: list[IndicatorSelection] = Field(..., min_length=1)
    financial_align: Literal["independent", "unified"] = "independent"
    unified_end_date: Optional[date] = None
    sort: Optional[BrowserSort] = None
    skip: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=500)
    include_aggregations: bool = True
    force_refresh: bool = False

    @model_validator(mode="after")
    def _validate_dates(self) -> BrowserExecuteRequest:
        if self.dates is not None and len(self.dates) > 5:
            raise ValueError("dates 最多 5 个截面日")
        return self


class BrowserColumnMeta(BaseModel):
    id: str
    label: str
    type: str = "string"
    unit: Optional[str] = None
    adjust: Optional[str] = None
    effective_date: Optional[str] = None
    effective_end_date: Optional[str] = None


class BrowserWarning(BaseModel):
    indicator_id: Optional[str] = None
    reason: str


class BrowserExecuteMeta(BaseModel):
    as_of_date: str
    effective_date: str
    effective_dates: list[str] = Field(default_factory=list)
    date_adjusted: bool = False
    universe_count: int
    indicator_count: int
    sort_applied: Optional[BrowserSort] = None
    multi_date_mode: bool = False


class BrowserAggregation(BaseModel):
    column_id: str
    sum: Optional[float] = None
    avg: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    count: int = 0


class BrowserExecuteResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    size: int
    columns: list[BrowserColumnMeta]
    meta: BrowserExecuteMeta
    aggregations: list[BrowserAggregation] = Field(default_factory=list)
    warnings: list[BrowserWarning] = Field(default_factory=list)
    code: Optional[str] = None
    cache_hit: bool = False


class IndicatorRef(BaseModel):
    id: str
    data_type: str
    column_key: str
    label: str
    domain: str
    data_type_label: str
    type: str = "string"
    unit: Optional[str] = None
    freq: Literal["static", "daily", "period"] = "static"
    date_column: Optional[str] = None
    supports_adjust: bool = False
    tags: list[str] = Field(default_factory=list)
    available: bool = True
    data_ready: bool = False
    group: Optional[str] = None
    pinyin: Optional[str] = None


class IndicatorTreeNode(BaseModel):
    id: str
    label: str
    node_type: Literal["domain", "group", "datatype", "indicator"]
    children: list[IndicatorTreeNode] = Field(default_factory=list)
    indicator: Optional[IndicatorRef] = None


class DimensionRef(BaseModel):
    id: str
    label: str
    description: Optional[str] = None
    category: str = "market"
    available: bool = True
    degraded: bool = False
    stock_count: Optional[int] = None


class BrowserTemplateItem(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_system: bool = False
    scope: Literal["system", "user", "team"] = "system"
    payload: dict[str, Any] = Field(default_factory=dict)


class BrowserMetaResponse(BaseModel):
    indicator_tree: list[IndicatorTreeNode]
    indicators_flat: list[IndicatorRef]
    dimensions: list[DimensionRef]
    dimension_categories: dict[str, str] = Field(default_factory=dict)
    system_templates: list[BrowserTemplateItem]
    domains: list[dict[str, str]]


class UniversePreviewRequest(BaseModel):
    universe: UniverseSpec


class UniversePreviewResponse(BaseModel):
    stock_count: int
    sample_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    is_estimate: bool = False


class BrowserExportRequest(BaseModel):
    query: BrowserExecuteRequest
    format: Literal["csv", "xlsx"] = "csv"
    async_job: bool = False


class BrowserExportResponse(BaseModel):
    job_id: Optional[int] = None
    download_url: Optional[str] = None
    content: Optional[str] = None
    snapshot_at: datetime
    message: str = ""


class BrowserTemplateCreate(BaseModel):
    name: str
    payload: dict[str, Any]
    description: Optional[str] = None


class BrowserTemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    scope: str
    is_system: bool
    payload: dict[str, Any]
    user_id: Optional[int] = None


class WatchlistCreate(BaseModel):
    name: str
    codes: list[str] = Field(default_factory=list)
    universe: Optional[UniverseSpec] = None


class WatchlistUpdate(BaseModel):
    name: Optional[str] = None
    codes: Optional[list[str]] = None


class WatchlistResponse(BaseModel):
    id: int
    name: str
    codes: list[str]


class BrowserTemplateUpdate(BaseModel):
    name: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    description: Optional[str] = None


class BrowserAuditItem(BaseModel):
    id: int
    user_id: Optional[int] = None
    universe_hash: str
    indicator_ids: list[str]
    as_of_date: str
    row_count: int
    duration_ms: int
    created_at: datetime


class BrowserAuditListResponse(BaseModel):
    items: list[BrowserAuditItem]
    total: int
    page: int
    size: int


class BrowserShareCreate(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class BrowserShareResponse(BaseModel):
    share_token: str
    expires_in_days: int = 7


class BrowserReadinessItem(BaseModel):
    data_type: str
    label: str
    level: Literal["p0", "p1"]
    activated: bool
    table_name: Optional[str] = None
    row_count: Optional[int] = None
    min_rows: Optional[int] = None
    ok: bool = False
    message: Optional[str] = None
    suggested_script: Optional[str] = None


class BrowserReadinessResponse(BaseModel):
    p0_ok: bool
    items: list[BrowserReadinessItem]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
