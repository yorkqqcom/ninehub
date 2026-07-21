"""Platform settings schemas."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PlatformSettingsResponse(BaseModel):
    sync_start_date: str
    sync_type_overrides: dict[str, Any]
    env_sync_start_date: str
    watch_alert_webhook_url: Optional[str] = None
    watch_alert_webhook_secret_masked: Optional[str] = None
    watch_alert_webhook_secret_configured: bool = False
    watch_alert_webhook_signature_version: str = "v2"
    watch_alert_webhook_active_source: Literal["db", "env", "none"] = "none"
    env_watch_alert_webhook_configured: bool = False


class PlatformSettingsUpdate(BaseModel):
    sync_start_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sync_type_overrides: Optional[dict[str, Any]] = None
    watch_alert_webhook_url: Optional[str] = None
    watch_alert_webhook_secret: Optional[str] = None
    watch_alert_webhook_signature_version: Optional[Literal["v1", "v2"]] = None
    watch_alert_webhook_clear: Optional[bool] = None


class WatchAlertWebhookTestResponse(BaseModel):
    ok: bool
    status_code: Optional[int] = None
    active_source: Literal["db", "env", "none"]
    detail: str
