"""TIA governance schemas."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TIAScanRequest(BaseModel):
    provider: str = Field(default="tushare", description="数据源供应方")
    mode: Literal["catalog", "full"] = Field(
        default="full",
        description="固定 full；catalog 仅 API 兼容",
    )
    index_scope: Literal["mixed", "stock_a"] = Field(
        default="stock_a",
        description="stock_a=股票数据类目; mixed=全菜单",
    )
    probe: bool = Field(default=True, description="是否执行 live API 探测")
    probe_scope: Literal["local_and_new", "all"] = Field(
        default="all",
        description="local_and_new=增量(本地+新增); all=全索引按 doc_id 遍历",
    )
    probe_limit: int = Field(default=500, ge=1, le=500, description="单次扫描最大探测数（probe_unlimited 时忽略）")
    probe_unlimited: bool = Field(
        default=False,
        description="true=探测不受 probe_limit 限制",
    )
    index_source: Literal["auto", "document2", "doc14", "bundled", "live"] = Field(
        default="document2",
        description="官方索引来源；UI 固定 document2，其余供脚本/测试",
    )
    sync_doc_pages: Optional[bool] = Field(
        default=None,
        description="全量扫描前同步 document/2 页面以重识别积分；null 时默认 false",
    )
    sync_doc_specs: Optional[bool] = Field(
        default=None,
        description="全量扫描前同步 wctapi markdown 入参/出参/示例；null 时 full=true",
    )
    sync_sdk_scan: Optional[bool] = Field(
        default=None,
        description="全量扫描前 SDK 包内省 + 批量校验 dataapi；null 时 full=true",
    )


class TIAScanJobResponse(BaseModel):
    job_id: int
    message: str = "Scan job queued"


class TiaDocPointsCoverageResponse(BaseModel):
    total_resolved_apis: int
    missing_min_points: List[Dict[str, Any]]
    stale_doc_pages: List[Dict[str, Any]]
    parse_gaps: List[Dict[str, Any]]
    bundled_mismatches: List[Dict[str, Any]]
    doc_id_conflicts: List[Dict[str, Any]]
    doc_id_multi_api: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="P0/P1：页面正文多接口或 cache.api 与正文不一致",
    )
    sidebar_drift: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="P2：sidebar 标签与页面正文 api 漂移（仅观测）",
    )
    audit_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="iteration-20 分层计数",
    )
    override_doc_ids: List[int]
    has_issues: bool


class TiaDocPagesSyncRequest(BaseModel):
    scope: Literal["resolved", "all"] = Field(
        default="all",
        description="resolved=仅 sidebar 已解析 doc_id；all=全菜单 doc_id",
    )
    doc_ids: list[int] | None = Field(default=None, description="指定 doc_id 列表（优先于 scope）")
    sleep_seconds: float = Field(default=0.35, ge=0.0, le=5.0, description="逐页抓取间隔秒数")
    use_playwright: bool = Field(default=True, description="使用 Playwright 渲染 Vue SPA")
    login_if_needed: bool = Field(
        default=True,
        description="无 storage 时用 TUSHARE_DOC_USERNAME/PASSWORD 登录",
    )
    rebuild_registry: bool = Field(default=True, description="同步后重建 tushare_api_by_doc_id.json")
    patch_sidebar: bool = Field(default=True, description="用抓取结果回写 document2_sidebar.json")
    reconcile_overrides: bool = Field(
        default=True,
        description="将 tia_overrides.min_points 与官网页面对齐",
    )
    dry_run: bool = Field(default=False, description="仅抓取合并预览，不写文件/DB")


class TiaDocAuthStatusResponse(BaseModel):
    configured: bool = Field(description="是否已配置用户名与密码")
    username: str | None = Field(None, description="当前生效用户名（不含密码）")
    has_password: bool = Field(description="是否已配置密码")
    credential_source: Literal["platform_file", "env", "none"] = Field(
        description="凭据来源：平台文件 / 环境变量 / 未配置"
    )
    storage_state_exists: bool = Field(description="Playwright 会话文件是否已存在")
    storage_path: str = Field(description="会话 storage 文件路径")
    credentials_path: str = Field(description="平台凭据文件路径")


class TiaDocAuthUpdateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128, description="Tushare 官网登录用户名/手机号")
    password: str = Field(..., min_length=1, max_length=256, description="Tushare 官网登录密码")


class TiaDocAuthVerifyResponse(BaseModel):
    ok: bool
    message: str
    storage_state_exists: bool = False
    storage_path: str | None = None
    preview_bytes: int | None = None


class TIAScanResultSummary(BaseModel):
    local_count: int
    official_count: int
    new_on_official: List[str]
    missing_from_official: List[str]
    unchanged: List[str]


class TIAScanJobDetailResponse(BaseModel):
    id: int
    job_type: str
    status: str
    progress: int
    message: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
