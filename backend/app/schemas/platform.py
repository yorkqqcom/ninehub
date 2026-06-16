"""Platform settings schemas."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class PlatformSettingsResponse(BaseModel):
    sync_start_date: str
    sync_type_overrides: dict[str, Any]
    env_sync_start_date: str


class PlatformSettingsUpdate(BaseModel):
    sync_start_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sync_type_overrides: Optional[dict[str, Any]] = None
