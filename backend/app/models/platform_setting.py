"""Platform settings singleton model."""

from typing import Any, Optional

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PlatformSetting(Base, TimestampMixin):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sync_start_date: Mapped[str] = mapped_column(String(10), default="2010-01-01")
    sync_type_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
    )
    watch_alert_webhook_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    watch_alert_webhook_secret: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    watch_alert_webhook_signature_version: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="v2",
        server_default="v2",
    )
