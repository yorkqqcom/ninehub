"""Data source schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import PageResponse

_PROVIDER_PATTERN = "^(tushare|akshare|tdx)$"


class TdxPathsConfig(BaseModel):
    vipdoc_root: Optional[str] = None
    hq_cache_root: Optional[str] = None
    concept_export_dir: Optional[str] = None
    connect_cfg_path: Optional[str] = None


class DataSourceConfig(BaseModel):
    token: Optional[str] = None
    account_points: Optional[int] = Field(None, ge=0, le=100000, description="Tushare 账户积分")
    max_calls_per_minute: Optional[int] = Field(
        None,
        ge=1,
        le=1000,
        description="可选：覆盖按积分推导的每分钟调用上限",
    )
    base_url: Optional[str] = Field(None, description="TDX Sidecar HTTP 基址")
    api_token: Optional[str] = Field(None, description="Sidecar Bearer Token")
    install_root: Optional[str] = Field(None, description="通达信安装路径")
    import_mode: Optional[str] = Field(default="file_first", description="file_first | network")
    paths: Optional[TdxPathsConfig] = None

    @field_validator("base_url")
    @classmethod
    def strip_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None


class DataSourceQuotaSummary(BaseModel):
    account_points: int
    max_calls_per_minute: int
    tier_max_calls_per_minute: int
    account_points_from_source: bool = False
    max_calls_from_override: bool = False
    env_account_points: int


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    config: DataSourceConfig = Field(default_factory=DataSourceConfig)
    status: str = Field(default="active", pattern="^(active|disabled)$")


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    provider: Optional[str] = Field(None, pattern=_PROVIDER_PATTERN)
    config: Optional[DataSourceConfig] = None
    status: Optional[str] = Field(None, pattern="^(active|disabled)$")


class DataSourceResponse(BaseModel):
    id: int
    name: str
    provider: str
    config: dict[str, Any]
    status: str
    quota: Optional[DataSourceQuotaSummary] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DataSourcePageResponse(PageResponse[DataSourceResponse]):
    pass


class DataSourceVerifyRequest(BaseModel):
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    token: Optional[str] = None
    source_id: Optional[int] = None
    base_url: Optional[str] = None
    api_token: Optional[str] = None
    install_root: Optional[str] = None


class DataSourceVerifyResponse(BaseModel):
    ok: bool
    message: str
    quota: Optional[DataSourceQuotaSummary] = None
    probe: Optional[dict[str, Any]] = None


class TdxProbeRequest(BaseModel):
    source_id: Optional[int] = None
    base_url: Optional[str] = None
    api_token: Optional[str] = None
    install_root: Optional[str] = None
    paths: Optional[TdxPathsConfig] = None


class TdxProbeResponse(BaseModel):
    ok: bool
    message: str
    status: dict[str, Any] = Field(default_factory=dict)
