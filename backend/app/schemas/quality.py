"""Quality schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.common import PageResponse


class QualityRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    rule_type: str = Field(pattern="^(min_rows|no_nulls)$")
    threshold: Optional[Decimal] = None
    target_data_type: str
    config_json: Optional[dict[str, Any]] = None
    is_enabled: bool = True


class QualityRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    rule_type: Optional[str] = Field(None, pattern="^(min_rows|no_nulls)$")
    threshold: Optional[Decimal] = None
    target_data_type: Optional[str] = None
    config_json: Optional[dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class QualityRuleResponse(BaseModel):
    id: int
    name: str
    rule_type: str
    threshold: Optional[Decimal] = None
    target_data_type: str
    config_json: Optional[dict[str, Any]] = None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QualityRulePageResponse(PageResponse[QualityRuleResponse]):
    pass


class QualityReportResponse(BaseModel):
    id: int
    data_type: str
    stock_code: Optional[str] = None
    status: str
    detail_json: Optional[dict[str, Any]] = None
    rule_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QualityReportPageResponse(PageResponse[QualityReportResponse]):
    pass


class QualityRunResponse(BaseModel):
    reports_created: int
    message: str
    alerts_sent: int = 0
    job_id: Optional[int] = None


class QualityRunRequest(BaseModel):
    data_type: Optional[str] = None
    stock_code: Optional[str] = None
    async_mode: bool = False
