"""Watch API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class WatchProfileOut(BaseModel):
    id: int
    name: str
    enabled: bool
    config_revision: int
    config_json: dict[str, Any]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WatchProfileCreate(BaseModel):
    name: str = "profile"
    config_json: Optional[dict[str, Any]] = None


class SetEnabledBody(BaseModel):
    enabled: bool


class ConfigPutBody(BaseModel):
    config_json: dict[str, Any]
    expected_revision: Optional[int] = None


class AlertOut(BaseModel):
    id: int
    profile_id: int
    symbol: str
    rule_id: str
    event_type: str
    payload_json: dict[str, Any]
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AlertListOut(BaseModel):
    items: list[AlertOut]
    total: int
    page: int
    size: int


class QuotesQuery(BaseModel):
    symbols: list[str] = Field(default_factory=list)
