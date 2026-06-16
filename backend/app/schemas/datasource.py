"""Data source schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.common import PageResponse


class DataSourceConfig(BaseModel):
    token: Optional[str] = None
    account_points: Optional[int] = Field(None, ge=0, le=100000, description="Tushare 账户积分")
    max_calls_per_minute: Optional[int] = Field(
        None,
        ge=1,
        le=1000,
        description="可选：覆盖按积分推导的每分钟调用上限",
    )


class DataSourceQuotaSummary(BaseModel):
    account_points: int
    max_calls_per_minute: int
    tier_max_calls_per_minute: int
    account_points_from_source: bool = False
    max_calls_from_override: bool = False
    env_account_points: int


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(pattern="^(tushare|akshare)$")
    config: DataSourceConfig = Field(default_factory=DataSourceConfig)
    status: str = Field(default="active", pattern="^(active|disabled)$")


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    provider: Optional[str] = Field(None, pattern="^(tushare|akshare)$")
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
    provider: str = Field(pattern="^(tushare|akshare)$")
    token: Optional[str] = None
    source_id: Optional[int] = None


class DataSourceVerifyResponse(BaseModel):
    ok: bool
    message: str
    quota: Optional[DataSourceQuotaSummary] = None
