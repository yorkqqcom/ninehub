"""Catalog schemas for task UI and dynamic type lists."""

from typing import List, Optional

from pydantic import BaseModel


class CatalogColumnMeta(BaseModel):
    key: str
    label: str
    type: str = "string"


class CatalogFilterMeta(BaseModel):
    key: str
    label: str
    filter_type: str


class DomainItem(BaseModel):
    key: str
    label: str


class DataBrowseResponse(BaseModel):
    items: List[dict]
    total: int
    page: int
    size: int
    data_type: str
    label: str
    domain: str
    table_name: Optional[str] = None
    columns: List[CatalogColumnMeta]
    filters: List[CatalogFilterMeta] = []


class DataTypeListItem(BaseModel):
    data_type: str
    domain: str
    label: str
    is_activated: bool
    browse_enabled: bool = False
    min_points: int
    chart_type: Optional[str] = None
    table_name: Optional[str] = None
    filters: List[CatalogFilterMeta] = []
    row_count: Optional[int] = None


class BrowseDomainCount(BaseModel):
    domain: str
    label: str
    count: int


class BrowseTypeSummary(BaseModel):
    total: int
    domains: List[BrowseDomainCount]


class DataTypeListResponse(BaseModel):
    items: List[DataTypeListItem]
    domains: List[DomainItem]
    summary: Optional[BrowseTypeSummary] = None


class DataStandardSummary(BaseModel):
    total: int
    full_match_count: int
    partial_match_count: int
    gap_count: int
    ddl_ready_count: int = 0
    schema_ready_count: int = 0
    activated_count: int = 0
    proposal_total: int = 0
    pending_count: int = 0
    applied_count: int = 0
    configured_count: int = 0
    template_count: int = 0
    unconfigured_count: int = 0
    drift_count: int = 0


class NamingComplianceItem(BaseModel):
    score: int
    issues: List[str]


class QualitySuggestionItem(BaseModel):
    rule_type: str
    target_data_type: str
    column: str
    reason: str
    config_json: dict = {}


class DriftDetailResponse(BaseModel):
    api_name: str
    data_type: str
    drift_status: str
    last_probe_at: Optional[str] = None
    doc_drift: dict
    live_drift: dict
    ddl_drift: Optional[dict] = None


class QualitySuggestionsResponse(BaseModel):
    api_name: str
    data_type: str
    suggestions: List[QualitySuggestionItem]


class DataStandardExportResponse(BaseModel):
    api_name: str
    data_type: str
    label: str
    format: str
    json_schema: Optional[dict] = None
    openapi: Optional[dict] = None


class DataStandardFieldItem(BaseModel):
    api_field: str
    standard_key: Optional[str] = None
    standard_label: Optional[str] = None
    standard_type: Optional[str] = None
    inferred_type: str
    status: str
    is_unique_key: bool = False


class DataStandardIndexItem(BaseModel):
    name: str
    columns: List[str]
    unique: bool = False
    purpose: str = ""


class DataStandardSummaryItem(BaseModel):
    api_name: str
    data_type: str
    label: str
    domain: str
    provider_id: str = "tushare"
    table_name: str = ""
    doc_id: Optional[int] = None
    doc_url: Optional[str] = None
    is_activated: bool = False
    proposal_id: int
    proposal_status: str
    proposal_reason: Optional[str] = None
    probe_status: str = "configured"
    probe_category: Optional[str] = None
    category: Optional[str] = None
    field_source: str
    schema_stage: str
    drift_status: str = "none"
    last_probe_at: Optional[str] = None
    naming_compliance: Optional[NamingComplianceItem] = None
    unique_keys: List[str]
    indexes: List[DataStandardIndexItem] = []
    unique_constraint: Optional[dict] = None
    api_field_count: int
    standard_field_count: int
    matched_count: int
    missing_count: int
    extra_count: int
    type_mismatch_count: int
    coverage_pct: float
    ddl_ready: bool = False
    ddl_errors: List[str] = []
    collect_pattern: Optional[str] = None
    collect_mode: Optional[str] = None
    pattern_mismatch: bool = False
    pattern_warnings: List[str] = []


class DataStandardDetailResponse(DataStandardSummaryItem):
    fields: List[DataStandardFieldItem]
    extra_fields: List[DataStandardFieldItem]
    field_mappings: dict[str, str] = {}


class DataStandardListResponse(BaseModel):
    items: List[DataStandardSummaryItem]
    total: int
    page: int
    size: int
    summary: DataStandardSummary


class CatalogCoverageSummary(BaseModel):
    local_count: int
    official_count: int
    unchanged_count: int
    new_on_official_count: int
    local_only_count: int
    coverage_pct: float
    official_index_source: str
    official_index_scope: str
    official_index_total: int


class CatalogCoverageItem(BaseModel):
    api: str
    reason: str


class CatalogCoverageResponse(BaseModel):
    summary: CatalogCoverageSummary
    new_on_official_sample: List[CatalogCoverageItem]
    local_only_sample: List[CatalogCoverageItem]
    unchanged_sample: List[CatalogCoverageItem]
